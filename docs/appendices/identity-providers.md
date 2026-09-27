# Appendix: OpenID Connect and LDAP sign-in

[Back to identity and credentials](../15-identity.md) · [Coverage](../COMMUNITY-COVERAGE.md)

## Goal

Sign in through a disposable identity provider, then give that identity a
separate project membership. Prefer OpenID Connect (OIDC) for this release;
read the LDAP limitations below before enabling a directory.

| Item | Edition and evidence |
| --- | --- |
| Edition | Community 2.19.12 |
| Tested with | RHEL 9.8, PostgreSQL 16; Dex 2.45.1; lldap 0.6.3-alpine-rootless |
| UI or API path | Provider button on the login page; `/api/auth/oidc/PROVIDER_ID/login`; `/api/auth/login` |
| Evidence | [Identity and roles](../validation/2026-09-community.md#identity-and-roles) |
| Known limits | The OIDC flow was tested with an HTTP client and cookies, not browser automation. LDAP skips certificate verification and its outage blocks new password logins, including local administrators. |

Prerequisites: complete [chapter 6](../06-semaphore.md), retain controller SSH
access and a working local Semaphore administrator, and prepare a private
[configuration recovery copy](../10-recovery.md). This optional fixture uses
Podman and EL9's operating-system `python3` with `crypt`; it is not a dependency
of the main guide. The fixture on Ubuntu, a real hosted IdP, HTTPS OIDC and
provider-wide logout were not tested.
Use the tested native baseline: Semaphore on `127.0.0.1:3000`, `web_host`
unset and LDAP disabled. This local fixture does not cover a controller already
configured with a public `web_host` or an HTTPS proxy.

The exercise creates one container, `/var/lib/semaphore-idp`, one provider
entry and one external practice user. Use a new user name and e-mail distinct
from every existing Semaphore account. Do not change your own login identity.

## Do: prepare a local Dex provider

**Where: controller, as root.**

Keep an administrator browser session open. Check that port 5556, directory
`/var/lib/semaphore-idp` and container `semaphore-idp-practice` are unused. The
campaign used this exact upstream Dex 2.45.1 image:

```text
ghcr.io/dexidp/dex@sha256:8499afd690c437f52301efd2b05b2455da5bd2dfc20332cd697dc9937f808462
```

Use separate credentials generated in your password manager for the Dex
practice user and the OIDC client. The client credential must be the same in
Dex and Semaphore. This script asks for both privately and stores the Dex
configuration inside a root-only directory. Its static password connector
stores a bcrypt hash; no reusable password appears in the command arguments.

```bash
install -d -m 0700 /var/lib/semaphore-idp
python3 <<'PY'
import crypt
import getpass
import json
import os

client = getpass.getpass('OIDC client credential: ')
password = getpass.getpass('Dex practice user password: ')
if not client or not password:
    raise SystemExit('Both credentials must be nonempty')
hashed = crypt.crypt(password, crypt.mksalt(crypt.METHOD_BLOWFISH, rounds=1 << 12))
if not hashed or not hashed.startswith('$2'):
    raise SystemExit('A bcrypt-capable operating-system Python is required')
cfg = {
    'issuer': 'http://127.0.0.1:5556/dex',
    'storage': {'type': 'memory'},
    'web': {'http': '127.0.0.1:5556'},
    'logger': {'level': 'info', 'format': 'json'},
    'oauth2': {'skipApprovalScreen': True, 'responseTypes': ['code']},
    'staticClients': [{
        'id': 'semaphore-practice', 'name': 'Semaphore practice',
        'secret': client,
        'redirectURIs': ['http://127.0.0.1:3000/api/auth/oidc/practice/redirect']
    }],
    'enablePasswordDB': True,
    'staticPasswords': [{
        'email': 'oidc-practice@idp.example.test', 'username': 'oidc-practice',
        'preferredUsername': 'oidc-practice', 'name': 'OIDC practice',
        'userID': 'OIDC_PRACTICE_ID', 'hash': hashed
    }]
}
path = '/var/lib/semaphore-idp/dex.json'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
with os.fdopen(fd, 'w') as f:
    json.dump(cfg, f)
os.chown(path, 1001, 1001)
PY
```

The tested image runs as UID 1001. Its configuration is readable by that UID;
the parent directory remains accessible only to root on the host. Start it
with the configuration's explicit loopback listener:

```bash
podman run -d --name semaphore-idp-practice --network host \
  --read-only --cap-drop=ALL --security-opt no-new-privileges --memory 128m \
  -v /var/lib/semaphore-idp/dex.json:/etc/dex/practice.json:ro,Z \
  ghcr.io/dexidp/dex@sha256:8499afd690c437f52301efd2b05b2455da5bd2dfc20332cd697dc9937f808462 \
  dex serve /etc/dex/practice.json
ss -ltn '( sport = :5556 )'
curl --fail --silent --show-error \
  http://127.0.0.1:5556/dex/.well-known/openid-configuration
```

Check that the listener is `127.0.0.1:5556` and discovery reports the issuer
`http://127.0.0.1:5556/dex`. These checks prove readiness, not successful sign-in.

## Do: connect Semaphore to Dex

**Where: controller, as root.**

Edit `/etc/semaphore/config.json` privately. Merge this block into the existing
JSON; preserve the database, encryption and other authentication settings.
Replace `CLIENT_SECRET` with the client credential entered above, using your
editor rather than a shell argument. Retain the file's service-readable
permissions from the installation guide; do not make it world-readable.

```json
{
  "oidc_providers": {
    "practice": {
      "display_name": "Dex practice",
      "provider_url": "http://127.0.0.1:5556/dex",
      "client_id": "semaphore-practice",
      "client_secret": "CLIENT_SECRET",
      "redirect_url": "http://127.0.0.1:3000/api/auth/oidc/practice/redirect",
      "scopes": ["openid", "profile", "email"],
      "username_claim": "preferred_username|name",
      "name_claim": "name",
      "email_claim": "email",
      "order": 1
    }
  }
}
```

`practice` is the provider ID in both API paths. The redirect URL must match
Dex's `redirectURIs` entry exactly. The 2.19.12 source tries the claim names
separated by `|` in order: the Dex user's `preferredUsername` supplies
`preferred_username`, which became the Semaphore username in the test, and
`name` is only the fallback.

Keep `password_login_disable` false or absent so the local sign-in form stays
available. Do not enable LDAP for this OIDC exercise. Validate without printing
the configuration and restart Semaphore:

```bash
python3 -m json.tool /etc/semaphore/config.json >/dev/null && \
  systemctl restart semaphore && systemctl is-active semaphore && \
  curl --fail --silent --show-error http://127.0.0.1:3000/api/auth/login
```

The login metadata should list **Dex practice** and `login_with_password: true`.

**Where: workstation, as your SSH administrator.**

For this fixture, forward the same two port numbers used in its URLs. Keep
both workstation ports free and leave this connection open. This supplements
the usual [private tunnel](browser-access.md#private-tunnel).

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:3000:127.0.0.1:3000 \
  -L 127.0.0.1:5556:127.0.0.1:5556 \
  YOUR_ADMIN@controller.example.test
```

The browser reaches Dex through the tunnel; Semaphore reaches Dex on the
controller's own loopback. Use `http://127.0.0.1:3000/` for this exercise so the
callback and the Semaphore browser session use the same origin.

## Check: identity before membership

**Where: browser, as the external practice user in a separate browser profile.**

Select **Dex practice**, enter `oidc-practice@idp.example.test` and the private
Dex password, then check the account and project list after returning.
The campaign completed the authorization-code flow and confirmed it with
`GET /api/user`, rather than trusting the callback redirect alone:

| Check | Observed result |
| --- | --- |
| First OIDC login | A session for a new external, non-administrator user; zero visible projects. |
| Semaphore logout | `POST /api/auth/logout` returned 204, then `GET /api/user` returned 401. |
| Second login | A working session for the same user ID, without a duplicate user. |
| IdP e-mail equals a local user's e-mail | Login refused; no authenticated Semaphore session and no automatic account linking. |

A matching e-mail is not an account migration procedure. With `web_host`
unset, the failed collision test redirected to the misplaced path
`/api/auth/oidc/PROVIDER_ID/auth/login`; return to the normal login page yourself.
Do not interpret that redirect as a working session.

**Where: browser, as the local Semaphore administrator.**

Confirm a fresh local password login still works, then add only the new
external account to a practice project through **Team**, as
[chapter 15](../15-identity.md) describes. Check the assigned role using the
external user's separate session. Authentication does not assign project
permissions. Automatic IdP group-to-role mapping is outside this Community
exercise; do not infer it from a successful login.

## Concept: LDAP limitations in 2.19.12

Prefer OIDC. **Semaphore 2.19.12 does not verify the LDAPS server certificate.**
The source sets `InsecureSkipVerify: true`; the test accepted an untrusted,
self-signed certificate that a verifying LDAP client rejected. Setting
`ldap_needtls` does not fix this, and `ldap_tls_skip_verify` is not a supported
remedy in this version. Do not use this result as a secure LDAP deployment recipe.

The isolated test used lldap **0.6.3-alpine-rootless**, upstream image
`docker.io/lldap/lldap@sha256:ba2c50930ea998eefd5454aa678a7977448019248b1827da87d330df0b71c284`,
with all three listeners on loopback. LDAP sign-in created an external user;
the second login found the same account, and a wrong password was refused.
These observations prove compatibility with that fixture, not Active Directory.

Two other findings affect the recovery plan:

- A directory user name equal to a local user's name locks that local account
  out: both its local password and the directory password were refused. Keep
  directory and local administrator names distinct before enabling LDAP.
- While the LDAP server is down, new password logins fail for everyone,
  including local administrators. The source searches LDAP before checking
  local credentials and returns on directory errors. The test confirmed new
  local-administrator and LDAP logins failed while an existing administrator
  session still worked. Keep a logged-in administrator session and controller
  SSH access; a local account alone is not sufficient fallback.

**Where: controller, as root, if recovering from an LDAP outage.**

Set `ldap_enable` to `false` in `/etc/semaphore/config.json`, validate its JSON
and restart `semaphore`. Confirm a fresh local administrator login before
closing the retained session. The campaign restored its original configuration
before new cleanup logins, then verified authentication settings were restored.

## Do: remove the practice provider

**Where: browser, as the local Semaphore administrator.**

Sign out the practice user, remove its practice-project membership and delete
only that external practice account through **Users**. Preserve existing users.

**Where: controller, as root.**

Remove only `oidc_providers.practice` from the configuration; remove the parent
`oidc_providers` key only if it is now empty. Validate the JSON and restart
Semaphore before removing Dex. Confirm a fresh local login works and the
practice provider no longer appears, then remove the fixture:

```bash
podman rm -f semaphore-idp-practice
rm /var/lib/semaphore-idp/dex.json
rmdir /var/lib/semaphore-idp
ss -ltn '( sport = :5556 )'
```

No listener should remain on port 5556. Close only the additional SSH tunnel
opened for this exercise. The campaign also removed its lldap fixture and
confirmed no provider listeners remained.
