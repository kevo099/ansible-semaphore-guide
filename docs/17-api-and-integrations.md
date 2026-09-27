# 17. API and integrations

[Previous: Semaphore operations](16-semaphore-operations.md) · [Next: runners](18-runners.md) · [Coverage](COMMUNITY-COVERAGE.md)

## Goal

Run a reviewed Ping template through the API, verify its output, and connect an
authenticated incoming webhook with fixed hosts and code.

| Edition and evidence | Scope |
| --- | --- |
| Edition | Community 2.19.12 |
| Tested with | ansible-core 2.21.4; RHEL 9.8 controller; Ubuntu 24.04 target |
| UI or API path | **API Tokens**, `/swagger`, `/api/project/PROJECT_ID/tasks`, **Integrations** |
| Evidence | [API and integrations](validation/2026-09-community.md#api-and-integrations), [task control](validation/2026-09-community.md#concurrency-and-task-control) |
| Known limits | Swagger is incomplete; webhook HTTP status does not prove dispatch; real provider delivery and retry deduplication not tested. |

Prerequisites: finish [chapter 6](06-semaphore.md), keep the
[private tunnel](appendices/browser-access.md#private-tunnel) on `127.0.0.1:8088` open,
and have Bash, curl, jq and an existing dedicated-user token for initial authentication.
Use a disposable **API practice Ping** template with one fixed inventory host,
reviewed repository ref, and run-time limit/branch overrides disabled. Qualify it first.

This exercise creates a named API token, task records, protected files, and an
integration with its own key and alias. Record these objects for scoped cleanup.
Keep existing project credentials.

## Do: inspect Swagger and token access

**Where: browser, as your dedicated Semaphore practice user.**

Open `http://127.0.0.1:8088/swagger`; it loaded without authentication in the
campaign. Its schema says **2.16.14** and omits token expiry, `X-Has-Next`, and
the incoming receiver. Use it for discovery; verify fields against responses and
the pinned 2.19.12 implementation.

A user API token acts as its user; it is not scoped to a project or resource.
Use a dedicated low-privilege user per integration, with membership only where
needed. Arrange it through [identity and roles](15-identity.md); keep resource
setup with the project owner. A token acts with its user's **current** project
role: in the campaign a demotion from Task Runner to Guest applied to the token
at once, and the next task launch was refused with 403.

The token API was tested directly; browser interaction was not tested. Source UI
labels: **API Tokens → New Token**, **Token Name**, **Expires**. Create
**api-practice** with a one-hour expiry using the recipe below. Use an unused
name and check workstation/controller clock agreement.

| Token operation | Tested contract |
| --- | --- |
| Create: `POST /api/user/tokens` | `name` and optional `expires_at` (UTC timestamp with `Z`); 201 returns the full token in `id`. Omitting expiry gives no expiry. |
| List: `GET /api/user/tokens` | Lists this user's tokens; `id` is only the first eight characters. |
| Authenticate: `GET /api/user` | Bearer token identifies its user; invalid, expired, or deleted token gets 401. |
| Delete: `DELETE /api/user/tokens/TOKEN_PREFIX` | Hard deletion by an ID prefix, at least eight characters; 204. No soft-revoke route exists in 2.19.12. |

Expiry is checked at login/authentication time, including each bearer request. A
short-lived token stopped working after expiry while its listed `expired` stayed
`false`. Past expiry at creation returned **400**. Check `expires_at` and an
authenticated request.

## Do: keep authentication private

**Where: workstation, as your own account, with the tunnel open.**

Use the same Bash session throughout. The hidden prompt and mode-0600 curl config
keep the token out of history and process arguments. Avoid verbose/trace output.
If a command prints `Stop:`, fix the cause before running the next block.

```bash
set +x
set -o pipefail
umask 077
practice_dir=$(mktemp -d)
api_config="$practice_dir/bootstrap.cfg"
api_base=http://127.0.0.1:8088/api
read -rs -p 'Existing dedicated-user API token: ' api_token
printf '\n'
if [[ $api_token =~ ^[A-Za-z0-9_=-]+$ ]]; then
  printf 'header = "Authorization: Bearer %s"\n' "$api_token" > "$api_config"
  chmod 0600 "$api_config"
else
  printf 'Stop: that does not look like an API token.\n' >&2
fi
unset api_token
api() {
  test -s "$api_config" || return 1
  curl --disable --config "$api_config" --fail --silent --show-error \
    --connect-timeout 5 --max-time 15 "$@"
}
api "$api_base/user" | jq '{id, username, admin}'
```

Check the username and that `admin` is false before continuing. Create the practice
token, switch to it, and discover the project/template by name. All IDs are yours.

```bash
jq -n '{name:"api-practice", expires_at:(now + 3600 | floor | todateiso8601)}' \
  > "$practice_dir/token-request.json"
api --header 'Content-Type: application/json' --data-binary @"$practice_dir/token-request.json" \
  --output "$practice_dir/token-created.json" "$api_base/user/tokens" ||
  printf 'Stop: the token was not created.\n' >&2
jq -er '.id | select(test("^[a-z0-9_=-]+$")) | "header = \"Authorization: Bearer \(.)\""' \
  "$practice_dir/token-created.json" > "$practice_dir/api.cfg" ||
  printf 'Stop: the new token could not be read.\n' >&2
chmod 0600 "$practice_dir/api.cfg"
api_config="$practice_dir/api.cfg"
api "$api_base/user/tokens" --output "$practice_dir/token-list.json"
api "$api_base/projects" | jq '.[] | {id, name}'
read -rp 'Practice project ID: ' project_id
[[ $project_id =~ ^[1-9][0-9]*$ ]] || printf 'Stop: enter a project number.\n' >&2
api "$api_base/project/$project_id/templates" | jq '.[] | {id, name, environment_ids}'
read -rp 'API practice Ping template ID: ' template_id
[[ $template_id =~ ^[1-9][0-9]*$ ]] || printf 'Stop: enter a template number.\n' >&2
read -rp 'Exact fixed inventory host alias: ' target_limit
jq -n --argjson template "$template_id" --arg limit "$target_limit" \
  '{template_id:$template, environment:"{}", params:{limit:[$limit]}}' \
  > "$practice_dir/task-request.json"
```

`template_id` selects the template. Optional `environment` is a JSON **string**
containing an object. `params` is an object; the tested `limit` is a string
array. The source defines `tags` and `skip_tags` as string arrays; these were
not tested here. Variable Groups (API: `environment`, `environment_ids`):
template `environment_ids` selects groups; task `environment` supplies extra
variables. Do not put `environment_ids` in a task creation body.

A locked template keeps its own limit and branch despite task overrides. The request
repeats the fixed host; the template controls it. Task extra variables can still
override group values: keep them empty here; see [inputs](14-inputs-and-templates.md).

## Do: launch and poll one task

Creation is not proof of execution. This poll has a two-minute budget plus the
active request's timeout. It never retries a launch or cancels on timeout.
Terminal statuses are `success`, `error`, and `stopped`.

```bash
poll_task() {
  local task_id=$1 deadline=$((SECONDS + 120)) status
  [[ $task_id =~ ^[1-9][0-9]*$ ]] || return 1
  while (( SECONDS < deadline )); do
    api "$api_base/project/$project_id/tasks/$task_id" \
      --output "$practice_dir/task.json" || return 1
    status=$(jq -er '.status | select(type == "string")' "$practice_dir/task.json") || return 1
    case "$status" in
      success|error|stopped)
        printf 'Task %s: %s\n' "$task_id" "$status"
        api "$api_base/project/$project_id/tasks/$task_id/raw_output" \
          --output "$practice_dir/task-output.txt" || return 1
        printf 'Read %s\n' "$practice_dir/task-output.txt"
        [[ $status == success ]]
        return ;;
    esac
    sleep 2
  done
  printf 'Polling ended; inspect task %s before taking further action.\n' "$task_id" >&2
  return 1
}
if api --request POST --header 'Content-Type: application/json' \
  --data-binary @"$practice_dir/task-request.json" \
  --output "$practice_dir/task-created.json" "$api_base/project/$project_id/tasks"; then
  task_id=$(jq -er '.id | select(type == "number" and . > 0)' "$practice_dir/task-created.json")
  poll_task "$task_id"
else
  printf 'Creation failed or is ambiguous: inspect task history before retrying.\n' >&2
fi
```

Even HTTP 500 can leave a task row: the campaign saw that with malformed inner
`environment` JSON. After any failed or ambiguous POST, reconcile history first.

## Check: read the effect and history

Read `task.json` and the saved output: confirm user ID, template, repository
ref, expected host and Ping recap. Match the user ID with `/api/user`. If the
recap is missing, refetch output after a short wait, at most five times: final
status can precede the last output. Missing output leaves the check incomplete.

| Read route, below `/api/project/PROJECT_ID` | Meaning |
| --- | --- |
| `/tasks/TASK_ID/output` | JSON log rows. |
| `/tasks/TASK_ID/raw_output` | Plain text; the campaign matched it to the log rows with ANSI removed. |
| `/stats`, `/templates/TEMPLATE_ID/stats` | Daily `count_by_status`; observed `avg_duration` was zero, and the source does not populate it. |
| `/tasks/TASK_ID/stages`, `/tasks/TASK_ID/ansible/hosts`, `/tasks/TASK_ID/ansible/errors` | Empty array or `null` in Community; 200 did not establish a working task summary. |

To page backward, request `/tasks/last?count=N`, save response headers, then use
the last returned task ID as `/tasks/last?count=N&before=ID`. Follow `X-Has-Next`
until `false` or an empty page; `before` selects strictly older IDs. For example:

```bash
api --dump-header "$practice_dir/page.headers" --output "$practice_dir/page.json" \
  "$api_base/project/$project_id/tasks/last?count=20"
jq '.[-1].id' "$practice_dir/page.json"
```

The campaign walked four pages without duplicates while no new tasks were
created. The source caps `count` at **200**; the small live dataset could not
prove the cap. `/templates/TEMPLATE_ID/tasks/last` also paged. Plain `/tasks`
has no cursor or `X-Has-Next`; its source limit is 1000 rows, so it is not a
full-history export.

If this practice task needs stopping, `POST /api/project/PROJECT_ID/tasks/TASK_ID/stop`
requires a JSON body: `{"force": false}`. No body returned **400** and the task kept
running. Poll afterward and inspect effects. Do not stop an already finished task:
that rewrote its status in testing. Force-stopping queued work could still let it
execute later; running-task descendants could survive either stop mode. Read
[task control](16-semaphore-operations.md) before using stop on changing playbooks.

A cross-origin session-cookie write returned **403 `CROSS_ORIGIN_REQUEST_BLOCKED`**.
Bearer writes passed that Origin check; this grants no extra project permissions.
Use private bearer configuration; keep browser cookies private and CSRF protection intact.

## Do: send an authenticated integration request

**Where: workstation, as the project owner, in a separate shell.**

Use the private curl-config pattern with the owner's credential; keep the
runtime user limited. The campaign tested Token authentication with a harmless
echo template; use your qualified Ping template here. Send these JSON objects
with the owner's authenticated client. Assemble credential input privately with
`read -rs` into a mode-0600 request file, then use `--data-binary @FILE`.

| POST route below `/api/project/PROJECT_ID` | Body fields and returned object |
| --- | --- |
| `/keys` | `project_id`, `name: "API practice webhook key"`, `type: "login_password"`, `login_password: {login: "", password: PRIVATE_INPUT}`. Save returned `id` as `KEY_ID`. |
| `/integrations` | `project_id`, `name: "API practice webhook"`, `template_id`, `auth_method: "token"`, `auth_header: "X-Practice-Token"`, `auth_secret_id: KEY_ID`, `searchable: false`. Save returned `id` as `INTEGRATION_ID`. |
| `/integrations/INTEGRATION_ID/aliases` | `{}`; 200 returns `{id, url}`. Retain the alias URL privately. |

Source UI equivalents: **Auth method → Token**, **Auth header**, **Vault
Password** (the key), **Use project alias** off, then **Add Alias**. Browser
setup was not tested. The key's Password is a separate webhook verification
value; use a generated nonempty alphanumeric value. The source can accept a
missing header against an empty configured value (not tested). Keep
task-parameter extractors out and preserve the template's host/ref gates.

**Where: workstation, as your own account, in the same Bash session.**

Enter only the alias segment at the hidden prompt; the config uses your known
tunnel origin.

```bash
read -rs -p 'Integration alias: ' hook_alias
printf '\n'
read -rs -p 'Webhook verification value: ' hook_value
printf '\n'
if [[ $hook_alias =~ ^[A-Za-z0-9]+$ && $hook_value =~ ^[A-Za-z0-9]+$ ]]; then
  printf 'url = "%s/integrations/%s"\nheader = "X-Practice-Token: %s"\n' \
    "$api_base" "$hook_alias" "$hook_value" > "$practice_dir/hook.cfg"
  chmod 0600 "$practice_dir/hook.cfg"
else
  printf 'Stop: the alias and value must be letters and digits.\n' >&2
fi
unset hook_alias hook_value
curl --disable --config "$practice_dir/hook.cfg" --silent --show-error \
  --connect-timeout 5 --max-time 15 --header 'Content-Type: application/json' \
  --data-binary '{}' --dump-header "$practice_dir/hook.headers" --output /dev/null \
  --write-out 'HTTP %{http_code}\n'
```

## Check: prove dispatch and refusal

**204 does not mean a task started.** Correct authentication, failed
authentication, and no matching integration all returned 204. Find
`X-Semaphore-Task-ID` in the saved headers, confirm that ID in the task list,
then use `poll_task ID` and inspect the Ping recap. Tested webhook tasks had
`user_id: null`; their key is not a user API token. An unknown alias returned an
empty **200**, with no task.

Repeat once with the `X-Practice-Token` header line removed from a copy of the
protected curl config. Expect 204, no task header, and no new task row. Inspect
history after an ambiguous response; do not retry webhook deliveries blindly.

| Other tested auth methods | Required form | Observed result |
| --- | --- | --- |
| HMAC | Chosen header; lowercase hex HMAC-SHA256 of exact body bytes, without prefix. | Valid body ran; changed body, wrong key, uppercase hex, missing header, and `sha256=` prefix started nothing. |
| BasicAuth | HTTP Basic matching the stored login and password. | Valid credentials ran; wrong login/password or missing credentials started nothing. |
| Bitbucket Webhooks | `X-Hub-Signature` with `sha256=` followed by lowercase HMAC-SHA256 hex. | Valid signature ran; wrong key or missing prefix started nothing. |
| GitHub Webhooks | `X-Hub-Signature-256` with the same prefixed form. | Valid signature and matching event ran; bad signature or event/branch mismatch started nothing. |

These were local provider-shaped requests; hosted GitHub/Bitbucket delivery was
not tested. Valid cases had a task header, new row and successful task; rejected
cases had neither header nor row despite 204.

## Concept: aliases and bounded inputs

A project alias dispatches to searchable integrations. The tested GitHub case
matched event, branch and repository fields. The source requires all matchers to
pass, and at least one matcher for a project alias. Zero-matcher refusal was not
tested. Individual aliases bypass matchers; enabling **Use project alias** made
the integration's own alias return 200 without a task. Filters are not
authentication.

Extractors copy headers or body data into task inputs. New keys reached Ansible
with an empty Variable Group; a JSON number became a string. Extracting a string
into the typed task `limit` array prevented dispatch while still returning 204.
Never map webhook fields into shell arguments or unrestricted variables.
Allowlist harmless data, retain the template's own limit/branch gates, and keep
**Task Params** extraction out of this exercise.

## Do: clean up and revoke

**Where: workstation, as the project owner, in the setup shell.**

DELETE `/api/project/PROJECT_ID/integrations/INTEGRATION_ID`, then
`/api/project/PROJECT_ID/keys/KEY_ID`, using only IDs recorded above. Deletion
removes the integration's individual aliases, matchers and extractors; project
aliases need separate deletion. Verify integration GET returns 404 and its list
entry is absent. After tasks finish and you retain output, remove the dedicated
template: this also removes task history. Remove the owner's temporary setup
files; retain the existing owner token.

**Where: workstation, as your own account, in the same Bash session.**

Hard-delete the practice token using its prefix, kept in a protected curl config.
An unknown prefix also returned 204; verify absence and a subsequent **401**.
The SQL source matches prefixes (including `_` as a wildcard); use this dedicated account.

```bash
jq -er --arg base "$api_base" '"url = \"\($base)/user/tokens/\(.id[0:8])\""' \
  "$practice_dir/token-created.json" > "$practice_dir/revoke.cfg"
api_config="$practice_dir/bootstrap.cfg"
revoke_practice_token() {
  local status
  api --config "$practice_dir/revoke.cfg" --request DELETE --output /dev/null ||
    { printf 'Stop: the delete request failed.\n' >&2; return 1; }
  status=$(curl --disable --config "$practice_dir/api.cfg" --silent --show-error \
    --connect-timeout 5 --max-time 15 --output /dev/null --write-out '%{http_code}' "$api_base/user")
  printf 'After deletion: HTTP %s\n' "$status"
  [[ $status == 401 ]] || { printf 'Stop: the deleted token still works.\n' >&2; return 1; }
  api "$api_base/user/tokens" | jq -e 'all(.[]; .name != "api-practice")' >/dev/null ||
    { printf 'Stop: the practice token is still listed.\n' >&2; return 1; }
}
if revoke_practice_token; then
  rm -r -- "${practice_dir:?}"
  unset practice_dir api_config
  unset -f api poll_task revoke_practice_token
else
  printf 'Kept %s so you can retry the revocation.\n' "$practice_dir" >&2
fi
```

## Concept: triggers and edition boundaries

Incoming integrations start tasks. Outgoing
[notification webhooks](16-semaphore-operations.md) report events to another service.
Paid audit webhooks described for 2.20+ are absent from this 2.19.12 source. Paid Pro
**Workflows**, including workflow approvals, are separate from Community task APIs.
External CI delivery, approval gates, malformed webhook bodies and duplicate-event
handling were not tested here. Keep public repository CI free of controller credentials.
