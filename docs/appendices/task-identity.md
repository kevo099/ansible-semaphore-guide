# Appendix: task identity with JWT and OpenBao

[Back to identity and credentials](../15-identity.md) · [Coverage](../COMMUNITY-COVERAGE.md)

## Goal

Use a task JWT to let one Semaphore template read a practice value from OpenBao
and refuse another template, without storing an OpenBao login token in Semaphore.

| Item | Scope |
| --- | --- |
| Edition | Community 2.19.12; custom integration, ungated in this version. |
| Tested with | ansible-core 2.21.4; RHEL 9.8 controller; OpenBao 2.7.0 in local dev mode. |
| UI or API path | Task Templates; `jwt_params` through `/api/project/PROJECT_ID/templates`; public `/.well-known/jwks.json`. |
| Evidence | [Task JWT campaign](../validation/2026-09-community.md#task-jwt-and-key-rotation): successful exchange, matching value digest, token revocation and negative cases. |
| Known limits | Live OpenBao test used local execution. Expired tokens, wrong issuer/audience, tampered signatures and remote-runner exchange were not tested. |

This is **not the paid native secret-storage integration**. The playbook calls
OpenBao's HTTP API itself, using only `ansible.builtin` modules.

## Do: prepare the practice objects

**Where: browser, as the practice project's administrator.**

Complete [the first Semaphore job](../06-semaphore.md) first. Use a reviewed
repository revision containing [openbao-jwt-read.yml](../../examples/semaphore/openbao-jwt-read.yml);
the earlier starter tag does not contain this new example. This optional exercise
needs controller root access, Python 3, curl and Linux Podman with host networking;
the main guide requires no container runtime.

Create a Static inventory named **JWT practice localhost**, containing only
`localhost ansible_connection=local`, with no SSH or sudo credential. Create two
Ansible Playbook templates, **JWT practice allowed** and **JWT practice denied**,
using that inventory, the reviewed repository and playbook path
`examples/semaphore/openbao-jwt-read.yml`. Leave prompts, extra CLI arguments,
schedules and privilege escalation off. Record their project and template IDs
from the URL or the [authenticated API](../17-api-and-integrations.md).

The fixture adds container `semaphore-bao-practice` and a private directory under
`/run`. Confirm that container name and loopback ports 8200/8201 are unused.

## Do: enable task JWT issuance

**Where: controller, as root.**

Keep a protected copy of the current Semaphore configuration. Merge this block
into `/etc/semaphore/config.json`, preserving all other settings and permissions:

```json
{
  "jwt": {
    "enabled": true,
    "issuer": "http://127.0.0.1:3000",
    "default_ttl": "10m",
    "max_ttl": "1h"
  }
}
```

The 2.19.12 application source sets the unconfigured default TTL to **1 hour**
and the maximum to **24 hours** (`util/config.go`, `util/jwt.go`). Set both
explicitly: a short default limits exposure if a token escapes, and a short
maximum limits template overrides. The campaign used the settings above and
`5m` on the allowed template. Expiration runs from issuance, not task completion.

Restart Semaphore when no jobs are running, then inspect its public key set:

```bash
systemctl restart semaphore
curl --fail --silent --show-error http://127.0.0.1:3000/.well-known/jwks.json
```

The campaign saw HTTP 404 while JWT was disabled, then one `EC`, `P-256`, `ES256`
signing key when enabled. This URL is at the web root, outside `/api`; it
publishes the public key, not a task token. Stop if the key set is unavailable.

**Where: browser, as the practice project's administrator.**

Edit both templates and enable **Issue JWT to task runner**. Set **JWT audience**
to `http://127.0.0.1:8200` on both. Set **JWT TTL** to `5m` on the allowed template
and leave it empty on the denied template. These source-checked 2.19.12 labels
appear after global enablement; the campaign configured them through the API.
The allowed template's API fragment is:

```json
{"jwt_params":{"enabled":true,"audience":["http://127.0.0.1:8200"],"ttl":"5m"}}
```

This fragment needs the other template fields for an update. The API returned
400 for `ttl: "2h"` against maximum `1h`, `audience: [""]`, and `ttl: "soon"`.
An empty audience *entry* is the tested rejection, not an absent list.

## Do: start the disposable verifier

**Where: controller, as root, in one Bash session.**

OpenBao dev mode is in-memory and for practice only. Never put its root token
on a command line: other local users can read arguments with `ps`. The image's
default entrypoint copies that token into arguments, so bypass it. Its dev banner
also prints the token; keep the container log in the root-only directory below.
Use no real credentials or operational data in this fixture.

```bash
umask 077
bao_practice_dir=$(mktemp -d /run/semaphore-bao.XXXXXX)
export bao_practice_dir
python3 - <<'PY'
import os, pathlib, secrets
p = pathlib.Path(os.environ['bao_practice_dir']) / 'root.env'
p.write_text('BAO_DEV_ROOT_TOKEN_ID=' + secrets.token_urlsafe(32) + '\n')
p.chmod(0o600)
PY
bao_image=quay.io/openbao/openbao@sha256:71156a1c6623a5fa3f5e61b0c6a8ead0faf0df29a778339188443551995d1315
podman pull "$bao_image"
podman run -d --pull=never --name semaphore-bao-practice --network host \
  --cap-drop=all --security-opt=no-new-privileges \
  --env-file "$bao_practice_dir/root.env" \
  --log-driver=k8s-file --log-opt="path=$bao_practice_dir/openbao.log" \
  --entrypoint /usr/bin/bao "$bao_image" \
  server -dev -dev-no-store-token -dev-listen-address=127.0.0.1:8200
curl --fail --silent --show-error --retry 10 --retry-connrefused \
  --retry-delay 1 http://127.0.0.1:8200/v1/sys/health
ss -ltn '( sport = :8200 or sport = :8201 )'
```

The digest pins OpenBao **2.7.0**. Check initialized, unsealed, version 2.7.0
health and listeners only on `127.0.0.1` (8200/8201). Stop if either check differs.

## Do: bind the role to the allowed template

**Where: controller, as root, in the same Bash session.**

OpenBao must reach Semaphore's JWKS URL. The issuer must exactly match
`bound_issuer`; the template audience must match `bound_audiences`. This
single-controller fixture shares the host network so both URLs use loopback.
With a remote runner, `localhost` in the playbook means the runner: the task
must reach OpenBao, and OpenBao must reach the controller's JWKS. That exchange
was not tested here; see [runner placement](../18-runners.md).

Enter your project and **JWT practice allowed** IDs. The code converts them to
JSON numbers, limits reads to one KV v2 path and prints a random value's digest.

```bash
read -rp 'Practice project ID: ' PROJECT_ID
read -rp 'Allowed template ID: ' TEMPLATE_ID
export PROJECT_ID TEMPLATE_ID
python3 - <<'PY'
import hashlib, json, os, pathlib, secrets, time, urllib.error, urllib.request
project_id, template_id = int(os.environ['PROJECT_ID']), int(os.environ['TEMPLATE_ID'])
assert project_id > 0 and template_id > 0
token = (pathlib.Path(os.environ['bao_practice_dir']) / 'root.env').read_text().strip().split('=', 1)[1]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def call(method, path, body=None):
    request = urllib.request.Request('http://127.0.0.1:8200/v1/' + path,
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={'X-Vault-Token': token, 'Content-Type': 'application/json'})
    with opener.open(request, timeout=20) as response:
        raw = response.read()
        return json.loads(raw) if raw else None
call('POST', 'sys/mounts/practicekv', {'type': 'kv', 'options': {'version': '2'}})
value = secrets.token_urlsafe(32)
for attempt in range(15):
    try:
        call('POST', 'practicekv/data/semaphore/demo', {'data': {'value': value}})
        break
    except urllib.error.HTTPError as error:
        if error.code != 400 or attempt == 14:
            raise
        time.sleep(1)
stored = call('GET', 'practicekv/data/semaphore/demo')['data']['data']['value']
assert stored == value
call('PUT', 'sys/policies/acl/semaphore-practice-read', {
    'policy': 'path "practicekv/data/semaphore/demo" { capabilities = ["read"] }'})
call('POST', 'sys/auth/semaphore-practice', {'type': 'jwt'})
call('POST', 'auth/semaphore-practice/config', {
    'jwks_url': 'http://127.0.0.1:3000/.well-known/jwks.json',
    'bound_issuer': 'http://127.0.0.1:3000'})
call('POST', 'auth/semaphore-practice/role/semaphore-practice-read', {
    'role_type': 'jwt', 'user_claim': 'sub',
    'bound_audiences': ['http://127.0.0.1:8200'], 'bound_claims_type': 'string',
    'bound_claims': {'project_id': project_id, 'template_id': template_id},
    'token_policies': ['semaphore-practice-read'], 'token_ttl': '5m', 'token_max_ttl': '10m'})
print('Expected SHA-256:', hashlib.sha256(value.encode()).hexdigest())
PY
```

**Use numeric JSON values in `bound_claims`.** Both tested roles used
`bound_claims_type: "string"` (exact matching), but only numeric ID values
worked. The pinned Semaphore docs used quoted numeric strings. That variant
returned 400 even for the allowed template, reporting a `project_id` mismatch.

## Check: prove the read and the refusal

**Where: browser, as a user allowed to run the practice templates.**

Run **JWT practice allowed**, with Dry Run and Diff off. Wait for the complete
recap. Compare its SHA-256 output with the setup digest. The playbook uses
`no_log: true` on every JWT, token and value handling task; it attempts token
revocation in an `always` block, including after a failed read. A failed
revocation fails the run. Process termination or lost connectivity can prevent
cleanup, so the OpenBao token also has a short TTL. Do not enable verbose
credential debugging or print the JWT to diagnose a censored failure.

Run **JWT practice denied** with the same audience and role. It must fail login
and print no digest. The campaign observed HTTP 400 with this exact error:

```text
error validating claims: claim "template_id" does not match any associated bound claim values
```

No OpenBao token was issued and no value read for that template. Then turn off
**Issue JWT to task runner** on the denied template and run again. The campaign
observed no `SEMAPHORE_JWT` and no login attempt. The public playbook fails its
private preflight; the campaign probe reported negative cases within successful tasks.

The live allowed run matched the stored value's digest, received a 300-second
OpenBao token and revoked it with HTTP 204. Its JWT lifetime was 300 seconds;
the other template inherited 600 seconds. Output scans found no raw value or JWT.
The public example has offline checks, not a separate live qualification.
Expiry and altered-token denials remain **not tested**.

## Do: clean up the exercise

**Where: browser, as the practice project's administrator.**

Delete the two **JWT practice** templates, then **JWT practice localhost**;
keep the pre-existing repository and other objects.

**Where: controller, as root, in the same Bash session.**

```bash
podman rm -f semaphore-bao-practice
rm -f -- "$bao_practice_dir/root.env" "$bao_practice_dir/openbao.log"
rmdir -- "$bao_practice_dir"
ss -ltn '( sport = :8200 or sport = :8201 )'
```

Confirm the container is absent and ports 8200/8201 have no listeners. Its in-memory
value, mounts and policies are gone. If no other template needs JWT issuance,
set `jwt.enabled` to `false` in the existing block and restart Semaphore when
idle; JWKS should return 404. Otherwise leave the block enabled deliberately.
Do not replace the whole configuration with an old copy over concurrent edits.

## Concept: a task identity is a credential

The source signs enabled tasks and supplies `SEMAPHORE_JWT` in their process
environment. Both global and template enablement are needed. Protect this
bearer credential even though its claims can be decoded.

| Claims in the 2.19.12 source | Meaning |
| --- | --- |
| `iss`, `aud` | Configured issuer and audience; one audience is a string, several an array. |
| `sub`, `task_id` | Subject `task:ID` and numeric task ID. |
| `project_id`, `template_id`, optional `user_id` | Numeric identities; `user_id` is omitted when no user is attached. |
| `iat`, `nbf`, `exp`, `jti` | Issue/not-before/expiry Unix timestamps and a random token ID; `iat` equals `nbf`. |

Bind the consumer's role to both project and template, and restrict its policy
to the required path. A claim identifies the template; it does not prove that
its playbook is trustworthy. Control who can edit that template and its code.
Task JWTs are distinct from Semaphore user API tokens and from an OpenBao root
token. Encryption-key maintenance belongs in [maintenance](maintenance.md).
