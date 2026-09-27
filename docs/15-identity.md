# 15. Identity, roles and credentials

[Previous: inputs and templates](14-inputs-and-templates.md) · [Next: schedules, notifications and task control](16-semaphore-operations.md) · [Coverage](COMMUNITY-COVERAGE.md)

## Goal

Give a person enough access to run approved automation, prove the limits, and
keep that person's sign-in separate from the credentials a task uses.

| Edition and evidence | This chapter |
| --- | --- |
| Edition | Community 2.19.12 |
| Tested with | RHEL 9.8 controller, PostgreSQL 16, ansible-core 2.21.4; variable-group probes also used an Ubuntu 24.04 target. |
| UI or API path | Users, Team, API Tokens, Key Store; `/api/auth`, `/api/user/tokens`, `/api/project/PROJECT_ID`. |
| Evidence | [Identity and roles](validation/2026-09-community.md#identity-and-roles), [inputs](validation/2026-09-community.md#inputs-and-templates), [API tokens](validation/2026-09-community.md#api-and-integrations). |
| Known limits | Guest can download backups; TOTP seeds are exposed to project members; tokens bypass TOTP; custom roles are paid only. |

Authentication answers **who you are**. A project role answers **what you may
do here**. An SSH key, sudo credential or Vault credential answers a different
question: what the running task can access. Signing in grants no project role.

## Do: choose a project role

**Where: browser, as the project owner.**

Use **Team** to grant access separately from creating an account. These are
the observed API results for ordinary users, without the global **Admin user**
flag. The UI label **Task Runner** corresponds to API role `task_runner`.

| Action | Owner (`owner`) | Manager (`manager`) | Task Runner (`task_runner`) | Guest (`guest`) | Non-member |
| --- | --- | --- | --- | --- | --- |
| View templates | 200 | 200 | 200 | 200 | 404 |
| Run a task | 201 | 201 | 201 | 403 | 404 |
| Read task output | 200 | 200 | 200 | 200 | 404 |
| Edit a template | 204 | 204 | 403 | 403 | 404 |
| Create a Key Store entry | 201 | 201 | 403 | 403 | 404 |
| List Key Store entries | 200 | 200 | 200 | 200 | 404 |
| Download project backup | 200 | 200 | 200 | 200 | 404 |
| Read team list | 200 | 200 | 200 | 200 | 404 |
| Update project settings | 204 | 403 | 403 | 403 | 404 |
| Add a team member | 204 | 403 | 403 | 403 | 404 |
| Delete project | 204 | 403 | 403 | 403 | 404 |
| Create a project globally | 401 | 401 | 401 | 401 | 401 |

Here 200/201/204 mean allowed, 403 means forbidden, and 404 makes the project
invisible to a non-member. Project creation was admin-only in the tested
configuration. Allowed role-probe tasks also completed successfully; the owner
deletion was checked by a subsequent 404.

Treat **Guest as “can read everything except secret values.”** Guests can read
task output, Key Store names, the team list and **download the project backup**.
Key Store reads and the backup did not return the stored credential canary.
This does not protect values printed into task output, nor the TOTP seeds
described below. Keep one project per trust group; do not use Guest for a person
who must not see the project's data.

Custom roles are **paid only**: the Community create endpoints are 404 stubs.
Per-template permission endpoints exist, but the attempted guest “run” grant
returned 400 and that guest still received 403 when starting either template.
The Community UI hides the permissions tab. Do not depend on that API to narrow
or extend a built-in project role.

## Do: create a local practice user

Prerequisites: finish [chapter 6](06-semaphore.md), keep an admin browser session
open, and prepare a disposable practice project with a working, harmless Ping
template and a fixed target limit. Use no schedules or external triggers in it.
This exercise creates one local user, one token and practice task records.

**Where: browser, as a Semaphore administrator.**

1. Open the account menu, **Users → New User**. Enter your own practice values
   for **Name**, **Username**, **Email** and **Password**. Leave **Admin user**
   and **External** unchecked. Enter the password privately, then **Save**.
2. In a separate browser profile, sign in as the new user. Confirm the practice
   project is absent before adding membership.
3. In the admin profile, open the practice project's **Team → New Team Member**.
   With invitations disabled, select **User**, select **Task Runner** as **Role**,
   then **Link**.

**Where: browser, as the practice user.**

Refresh, open **Task Templates**, launch the Ping template and choose **Run**.
Read its completed output: verify the intended target, `changed=0`, no failures.
Check that template editing is unavailable. The UI labels come from the pinned
source; the campaign tested role enforcement through separate API sessions.
The browser exercise above was not independently recorded in that campaign.

## Check: prove the same limits with a token

**Where: browser, as the practice user.**

Open the account menu, **API Tokens → New Token**. Give it a **Token Name** such
as `Identity practice`, choose a short **Expires** period using **Custom**, and
select **Create**. Copy it privately now: later lists show only an **8-character
prefix**, not the reusable token. These form labels are source-verified.

**API tokens bypass TOTP.** A verified user can create one; an unverified TOTP
session cannot. Anyone holding that token can act as its user without a TOTP
code. Use a dedicated user with limited membership, set expiry, and revoke it
when the exercise ends. Tokens are case-insensitive; changing case does not
create a different credential.

**Where: workstation, in Bash, as your ordinary account.**

Keep the [private tunnel](appendices/browser-access.md#private-tunnel) open.
Read the project and template numeric IDs from their browser URL. The following
commands keep the bearer credential out of curl's arguments and shell history.
Use this same shell through cleanup; do not enable shell tracing.

```bash
set +x
umask 077
API_DIR=$(mktemp -d)
trap 'rm -rf -- "$API_DIR"' EXIT
BASE=http://127.0.0.1:8088
read -r -p 'Practice project ID: ' PROJECT_ID
read -r -p 'Practice template ID: ' TEMPLATE_ID
[[ "$PROJECT_ID" =~ ^[0-9]+$ && "$TEMPLATE_ID" =~ ^[0-9]+$ ]] ||
  printf 'Both IDs must be numbers; enter them again.\n' >&2
read -rs -p 'Practice API token: ' PRACTICE_TOKEN
printf '\n'
printf 'header = "Authorization: Bearer %s"\n' "$PRACTICE_TOKEN" > "$API_DIR/curl.conf"
unset PRACTICE_TOKEN
curl --config "$API_DIR/curl.conf" --fail --silent --show-error \
  "$BASE/api/project/$PROJECT_ID/role"
printf '{"template_id":%s}\n' "$TEMPLATE_ID" > "$API_DIR/task.json"
curl --config "$API_DIR/curl.conf" --silent --show-error \
  -H 'Content-Type: application/json' --data-binary @"$API_DIR/task.json" \
  --output "$API_DIR/task-response.json" --write-out '%{http_code}\n' \
  "$BASE/api/project/$PROJECT_ID/tasks"
```

Expect role `task_runner`, permissions `1`, and HTTP 201. Open the new task in
the browser and check its full Ping output, not only its creation response.

To check edit denial, retrieve the practice template and try to PUT that same
definition back. Keeping it unchanged avoids a configuration change if you
accidentally chose an overprivileged token; a 204 is still a failed access test.

```bash
curl --config "$API_DIR/curl.conf" --fail --silent --show-error \
  --output "$API_DIR/template.json" \
  "$BASE/api/project/$PROJECT_ID/templates/$TEMPLATE_ID"
curl --config "$API_DIR/curl.conf" --silent --show-error --request PUT \
  -H 'Content-Type: application/json' --data-binary @"$API_DIR/template.json" \
  --output /dev/null --write-out '%{http_code}\n' \
  "$BASE/api/project/$PROJECT_ID/templates/$TEMPLATE_ID"
```

Expect 403. A 400 means a malformed request, not proof of role enforcement.

**Where: browser, as the practice project's owner.**

In **Team**, change the practice user's **Role** to **Guest**.

**Where: workstation, in the same Bash shell.**

Repeat the role GET and task POST above using the same token. Expect `guest`,
permissions `0`, and 403; confirm no new task appeared. The campaign observed
this immediately: tokens use the user's **current** project role.

**Where: browser, as the practice user, then as the administrator.**

Delete this token with its trash icon in **API Tokens**. Using the same protected
curl config, a subsequent `GET /api/user` must give 401. Revocation took effect
immediately in the campaign. Expiry also produced 401 after `expires_at`; a past
expiry was rejected with 400. The list's `expired` field stayed false in one
expiry test, so test an authenticated request instead of trusting that field.

Remove the practice membership in **Team**, then delete only the practice user
in **Users**. Keep any project you used as a prerequisite; remove a project only
if you created it solely for this exercise. Delete the temporary local files:

**Where: workstation, in the same Bash shell.**

```bash
rm -rf -- "$API_DIR"
trap - EXIT
unset API_DIR BASE PROJECT_ID TEMPLATE_ID
```

## Do: select the right secret mechanism

**Where: browser, as the project owner or manager.**

| Mechanism | Purpose and boundary | Where to continue |
| --- | --- | --- |
| Key Store entries | **SSH Key** or **Login with password** credentials for tasks. In this guide they are encrypted using the controller's `access_key_encryption` key; the API does not return their secret values. Protect the database and encryption key together. | Reuse [chapter 6, step 2](06-semaphore.md#step-2-add-credentials-in-key-store); keep a sudo entry's **Username empty** as that step explains. |
| Variable Groups, **Secrets** | API `environment`: `var` supplies an Ansible extra variable; `env` supplies a process environment variable. Both reached the play; values were absent from API reads. They are not separate entries in the visible Key Store list. | [Inputs and templates](14-inputs-and-templates.md). |
| Ansible Vault files | Encrypted files that Ansible must unlock; inventory placement and service read access still matter. Keep the unlocking credential separate. | [CLI Vault use](07-git-and-vscode.md#do-add-variables-without-adding-secrets) and [3b's per-target sudo option](03-controller-el9.md#do-give-the-templates-the-targets-sudo-password). |
| Task JWT with an external store | A task identity used by a custom integration to request external data; distinct from a person's Semaphore API token. | [Task identity appendix](appendices/task-identity.md). |

**Variable-group secrets are not masked if printed.** The campaign's harmless
canary appeared in both normal and raw task output. Ansible `no_log: true`
suppressed the corresponding task output. Avoid printing credentials; apply
`no_log` to tasks that handle them and review output before granting access.
Guests can read those logs.

The process checks also found `var` values in Ansible's command line, readable
by another local account. `env` values were in the process environment, readable
by root in the test. Neither mechanism isolates secrets from the execution
host. Restrict local access and run reviewed playbooks. See chapter 14 for input
handling, including the tested space-splitting limit on variable-group `var`.

Native external **Secret Storage**, including the Vault/OpenBao UI integration,
is **paid only** in 2.19.12. It is separate from Ansible Vault files and the
custom task-JWT integration. The pinned Community source disables those native
feature flags; this chapter does not teach that paid path.

## Do: prepare TOTP recovery before enrolment

TOTP works in Community 2.19.12, with limits that affect who you can trust:

| Observed limit | Safe practice |
| --- | --- |
| **Every project member, guests included, can read another member's TOTP seed** through `GET /api/project/PROJECT_ID/users/USER_ID`. Admins can read it too. | Keep one project per trust group. TOTP here protects against a leaked password from outside, **not against other project members**. Do not publish user responses, QR images or seeds. |
| The same correct code worked in a second session within its time window: no replay protection. | Keep codes private and short-lived; do not rely on “already used” to make an exposed code harmless. |
| Setting `mfa.totp.enabled` to `false` silently removes the second factor for enrolled users. | Keep it enabled while any account relies on it; use per-user removal for recovery. |
| API tokens bypass TOTP. | Protect, expire and revoke tokens independently. |

Prerequisites: a disposable local user, a private browser connection, an
authenticator app, controller configuration access, and a separate logged-in
administrator who can remove that user's TOTP. The exercise adds a TOTP
enrolment and temporarily changes the `mfa.totp` settings.

**Where: controller, as root.**

Privately back up `/etc/semaphore/config.json` with its existing ownership and
permissions. Merge this fragment into its existing `mfa` object, preserving
other settings:

```json
{
  "mfa": {
    "totp": {
      "enabled": true,
      "allow_recovery": true,
      "app_name": "Semaphore"
    }
  }
}
```

Validate before restarting; continue only if both commands succeed:

```bash
python3 -m json.tool /etc/semaphore/config.json >/dev/null && systemctl restart semaphore
```

The API enrolment issuer is always **Semaphore**, regardless of `app_name`.
The pinned CLI has a separate issuer setting; that CLI flow was not tested here.
E-mail one-time codes are **paid only**: the source has a verification stub;
the campaign did not test that path.

**Where: browser, as the disposable user; keep the admin session open.**

Open **Edit Account → Security → Two-factor authentication → Time-based
one-time password**. The source shows that its toggle enrols through
`POST /api/users/USER_ID/2fas/totp`. **On PostgreSQL this answered 400 even
though the TOTP was stored, and no recovery code reached the user.** Do not
retry blindly or assume `allow_recovery` gave you a usable recovery code.
The source shows that reopening the account form loads the stored enrolment
and its QR; that browser recovery was not tested. Scan the QR privately if it
is displayed. The campaign independently fetched a working QR image after the 400.
If you cannot obtain the QR, have the admin remove the enrolment before leaving.

## Check: verify a fresh TOTP login and removal

Log out and sign in again. A session opened before enrolment kept working in
the test, so it is not proof that the second factor is active. Password-only
login creates a pending session, but protected API requests return
401 `TOTP_REQUIRED`. A wrong code returns 401 `INVALID_PASSCODE`; a correct code
through `POST /api/auth/verify` permits a working authenticated session.
Confirm you reach your account after entering the correct code.

Keep this recovery route available: the administrator can remove the affected
user's TOTP with **`DELETE /api/users/USER_ID/2fas/totp/TOTP_ID`**. The pinned
source permits self or admin removal. The campaign used that DELETE route
because no recovery code was returned; a fresh password-only login then worked.
Read the enrolment ID privately; never copy its seed into a support message.

Cleanup: remove only the practice user's enrolment, prove a fresh password-only
login works, then remove that disposable user. Restore only settings changed
for this exercise and restart from the controller as root, **only if no other
user now depends on TOTP being enabled**. Do not disable everyone's second factor
as routine cleanup.

## Concept: sign-in is not project access

OIDC and LDAP are also observed Community capabilities in this release. Prefer
OIDC; the [identity-providers appendix](appendices/identity-providers.md) covers
the isolated exercise and LDAP's certificate, account-collision and outage
limits. After any sign-in method, assign project membership deliberately and
repeat the allowed/denied checks before giving the user automation access.
