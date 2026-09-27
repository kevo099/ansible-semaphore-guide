# Validation record: Semaphore Community features, September 2026

[Back to validation and limits](../VALIDATION.md) · [Community coverage](../COMMUNITY-COVERAGE.md)

This page records the live campaign of 27 September 2026 that requalified the
guide on ansible-core 2.21.4 and then exercised every Semaphore capability the
earlier research had classified as free in Community 2.19.12. It is the
evidence behind chapters 14 to 18, the appendices and the
[coverage table](../COMMUNITY-COVERAGE.md).

## How the campaign ran

- **Controller:** a registered RHEL 9.8 VM with 2 vCPUs and 3 GiB RAM, SELinux
  enforcing, installed from this guide's branch with
  `install-controller-el9.sh`: Semaphore Community 2.19.12, PostgreSQL 16 and
  ansible-core 2.21.4.
- **Target:** an Ubuntu 24.04 VM attached to Ubuntu Pro, prepared with chapter
  4's steps. The runner tests later used it as the runner host too.
- **Method:** one test module per feature group, each written from the pinned
  2.19.12 source and run against the live server through its API and command
  line, with the request bodies the 2.19.12 UI sends. Every module recorded
  what it observed, including failures, and restored the settings it changed.
  Both VMs were rolled back to their starting snapshots afterwards.
- **Practice services** ran in Podman on the controller, on loopback only,
  pulled by digest through a local pull-through cache: Mailpit (e-mail), Dex
  (OpenID Connect), lldap (LDAP) and OpenBao 2.7.0 (task JWT). Webhook
  notifications went to a local capture listener.
- **Secrets:** every password, token and key was generated for the run and
  passed on standard input; none appears in the records.

Each capability below is classified on two separate axes: its **edition**
(works in Community 2.19.12, paid only, or not present in 2.19.12) and the
**live result**. A capability can be free and still behave in a way you need
to plan around; those findings are listed as sharp edges.

## Rehearsal of the new chapters

After the feature tests, the new chapters' own example files and fenced
command blocks were run as written on the same controller, read straight from
this branch. UI steps were made through the API with the bodies the UI sends.

| Page | What ran as written | Result |
| --- | --- | --- |
| [Inputs and templates](../14-inputs-and-templates.md) | The copy block, both variable groups, the survey and `input-demo.yml` | Passed: markers `second`/`second`/`blue`/`2`; survey `green`/`3`/`survey`; count 4 failed its assertion. |
| [Other task apps](../appendices/other-apps.md) | The file, state-directory and runtime blocks; Bash and Python templates; the OpenTofu template and state check | Passed: exit 0 and 3 behaved as described; plan and confirm, unchanged, reject, plan only, auto-approve and destroy all matched. |
| [Identity](../15-identity.md) | The token shell session as a Task Runner, the demotion and the revocation | Passed: `task_runner`, 201 then 403 for the edit; `guest` and 403 after demotion; 401 after deletion. |
| [Operations](../16-semaphore-operations.md) | The copy block, the local inventory, `operations-pause.yml` and `operations-failure.yml`, one plain Stop on a queued run, a one-time schedule | Passed: the second run waited; the stopped queued run never started; the one-time schedule ran once and became inactive. |
| [API and integrations](../17-api-and-integrations.md) | The whole shell session: token bootstrap, launch and poll, paging, the token-authenticated webhook, an unauthenticated repeat, revocation | Passed: one task from the API and one from the webhook, none from the unauthenticated repeat, 401 after revocation. |
| [Task identity](../appendices/task-identity.md) | The JWT, JWKS, OpenBao and role blocks and `openbao-jwt-read.yml` | Passed: matching digest for the allowed template; the other template refused with the claim error; no JWT or value in any log. |
| [Runners](../18-runners.md) | Every block on an Ubuntu 24.04 runner host (co-located with the target): HTTPS exposure, the checksum-verified install, account, configuration, unit, one-time registration, the runner inventory and template, the offline wait and the removal | Passed: Ping ran on the runner and its journal recorded the task; a task waited while the runner was offline and completed when it returned; the runner was deleted and the controller returned to loopback. |
| [Maintenance](../appendices/maintenance.md) and [syslog](../16-semaphore-operations.md#do-send-service-logs-to-syslog) | The export and import block; the syslog fragment, restart and `journalctl` check | Passed: the imported project had its eleven templates and empty keys, and its Ping failed with `secret must be valid json`; the syslog check matched the task's queue line. The key-file creation and check blocks also ran as written; the rotation itself follows the tested module sequence and was not rehearsed separately. |

The rehearsal and the review of the drafts found and fixed these defects
before publication:

- A `curl` right after `systemctl restart semaphore` met a closed port; the
  blocks now retry until Semaphore listens again.
- The runtime check ran `tofu --version` as the service account from root's
  working directory, which that account cannot read; it now changes to `/`.
- The OpenBao example hid the refusal reason with `no_log`; it now reports
  OpenBao's status and error text, which carry no credential.
- Command blocks meant for an interactive shell used `exit` or a top-level
  `set -e`, which would have closed the reader's terminal on the first error;
  they now print a `Stop:` message or run in a subshell (found in review).

## Platform and edition baseline

- `semaphore version` and `/api/info` both reported 2.19.12 Community.
- Every paid feature flag was false, and `GET /api/subscription` answered 404,
  the Community stub.
- `/api/apps` enabled exactly the apps whose binaries were on the service's
  `PATH`: `ansible` and `bash` on a fresh install. Installing OpenTofu and
  Terragrunt and restarting the service activated them. Python is not detected
  that way; it needed `"apps": {"python": {"active": true}}` in `config.json`.

## ansible-core 2.21.4 requalification

Guide commit `542c76b`, which changes only the core pin; the resolved
dependency set is otherwise identical.

| Check | Result |
| --- | --- |
| Ubuntu installer on Ubuntu 24.04 | rc 0; `ansible [core 2.21.4]`; the virtual environment matched the pins exactly; readiness passed. |
| Enterprise Linux installer on RHEL 9.8 | The same, plus seeding: eleven templates; `add-target.sh` added the Ubuntu target with its verified host key. |
| Ping | success, `ok=8 changed=0` |
| Baseline preview, apply, repeat | success; `changed=2`, `changed=2`, then `changed=0` |
| Users, repeat | success; `changed=2`, then `changed=0` |
| Webserver, repeat | success; `changed=5`, then `changed=0` |
| Patch preview, no reboot, allow required reboot | success; the operating system requested no reboot, so the approved-reboot path did not reboot |
| STIG audit (Ubuntu Security Guide) | success; 66 failing and 55 passing rules |
| STIG apply, allow required reboot | success; remediation applied, target rebooted, then Ping and a `changed=0` Baseline preview succeeded |

Not rerun on 2.21.4: AlmaLinux, Rocky Linux or RHEL targets, the Ubuntu manual
path, chapter 10's restore and the seeded **STIG apply (vendor fixes, approval
required)** template; its reboot variant ran.

## Inputs and templates

Chapter: [inputs and templates](../14-inputs-and-templates.md).

| Capability | Edition | Live result |
| --- | --- | --- |
| Several variable groups per template (`environment_ids`) | Community | Passed. Values from all groups reached the play. |
| Legacy `environment_id` | Community, deprecated | Accepted and converted to a one-item list. |
| Variable-group secrets, `var` and `env` types | Community | Passed. Both reached the play; the API never returned a value. |
| Survey variables: string, integer, text, enum, defaults, `env` target | Community | Passed. Integers arrive as strings. |
| Limit, branch and argument overrides | Community | Applied when the template allows them; silently ignored when it does not. |
| Template views | Community | Not tested; the source shows they only organize the template list. |
| Bash and Python templates | Community | Passed. The exit code sets the task status (exit 3 gave `error`). |
| Build and Deploy templates | Community | Passed: numbered builds, autorun deploys, a manual deploy of an older build. A requested build version of 9.9.9 was replaced by the next number, 1.0.1. |

Sharp edges found:

- **Group order is by id.** When two groups define the same key, the group
  created later wins, whatever order you list them in.
- **Printed secrets are not masked.** A secret the play prints appears
  verbatim in the task log. Only Ansible's `no_log` hides it.
- **`var` secrets and survey values are on the command line.** Group `var`
  secrets are passed to `ansible-playbook` as separate `--extra-vars
  name=value` arguments; extra-variable survey values, survey secrets included,
  are passed in JSON. Both were visible to an unrelated, non-`semaphore` local
  account in the process list while the task ran. Group `env` secrets and
  environment-target survey values were in the process environment, readable
  by root and the service account but not by that account. A group `var`
  secret containing a space was split; the survey secret kept its space.
- **Survey values are evaluated as templates.** A value of
  `{{ lookup('ansible.builtin.pipe', 'id -un') }}` ran on the controller as the
  service account.
- **Survey rules are enforced by the UI only.** Through the API, a required
  field could be omitted and an integer or enum field given any value.
- **Bad task input returns HTTP 500**, not 400. Malformed embedded
  `environment` JSON left an error task row; wrong-typed `params` created no
  task row. Only a malformed JSON request body returned 400.
- A local-folder repository has no branches: Semaphore runs its working tree,
  so a branch override needs a real Git repository.

## Other task apps

Appendix: [other task apps](../appendices/other-apps.md).

| App | Edition | Live result |
| --- | --- | --- |
| OpenTofu | Community | Passed: plan, pause at `waiting_confirmation`, confirm and apply; reject; an unchanged plan finishing without confirmation; plan only; auto-approve; destroy. |
| Terragrunt | Community | Passed: plan through OpenTofu. |
| Terraform (HashiCorp) | Community | Not tested; it uses the same code path as OpenTofu. |
| PowerShell | Community | Not tested; PowerShell was not installed. |
| Pulumi | Not present in 2.19.12 | A template using it was refused as an invalid app. |
| Semaphore-managed Terraform state | Paid only | Endpoints are stubs. |
| Task stage summaries | Paid only | Stub; nothing recorded. |

## API and integrations

Chapter: [API and integrations](../17-api-and-integrations.md).

| Capability | Edition | Live result |
| --- | --- | --- |
| API tokens: create, list, bearer use, expiry, revoke | Community | Passed. An expiry already in the past was refused with 400; a 20-second token stopped working within a second of its expiry. |
| Cross-origin session cookie (CSRF) | Community | Refused with 403. |
| Swagger UI at `/swagger` | Community | Served without login. Its embedded description says 2.16.14 and omits newer fields. |
| Keyset paging on `/tasks/last` | Community | Passed: `count` and `before`, `X-Has-Next`, no repeats. |
| Integrations with token, HMAC, basic, Bitbucket and GitHub authentication | Community | Each started exactly one task with valid credentials and none for the invalid cases exercised; missing credentials were tested for token, HMAC and basic authentication. |
| Matchers and extractors | Community | Passed: non-matching events started no task; extracted values reached the play. |

Sharp edges found:

- **The receiver answers 204 whether or not a task started**, including for a
  wrong secret. The `X-Semaphore-Task-ID` response header, or the task list,
  identifies an accepted task; poll it to a terminal status and read its
  output to prove it ran. An unknown alias gets an empty 200.
- An extractor that wrote a string into the task's limit, which is a list,
  made every request start no task, still answering 204.
- A token acts as its user with that user's current role; see
  [identity and roles](#identity-and-roles).

## Schedules

Chapter: [schedules, notifications and task control](../16-semaphore-operations.md).

| Capability | Edition | Live result |
| --- | --- | --- |
| Cron schedules and `@every` | Community | Passed: the timed checks created task records within 0.01 s of the due time; execution can then wait in the queue. `@hourly` passed syntax validation only. |
| One-time schedules (`run_at`), delete after run | Community | Passed: one run, then the schedule was deactivated or deleted. |
| Task parameters on a schedule | Community | Passed, subject to the template's override settings. |
| Enable and disable ordinary schedules | Community | Passed; no run after disabling. |
| Commit-check schedules | Community | Passed with a caveat: the first poll ran the template, an unchanged repository did not, a new commit did. Setting `active: false` did **not** stop the checker; clearing the template's checkbox removes it. |
| `schedule.timezone` and a `CRON_TZ=` prefix | Community | Passed; the service's own `TZ` was ignored. |

Sharp edges found:

- Schedules use `schedule.timezone`, UTC by default, not the server's zone.
- **A one-time schedule drops the UTC offset you send.** `17:16+05:45` was
  stored as `17:16Z`; send UTC with `Z`, as the UI does.
- **A schedule `PUT` clears the fields you leave out**, including its active
  flag and task parameters.
- A commit-check schedule is not shown in the project's schedule list, only on
  its template.

## Notifications

| Capability | Edition | Live result |
| --- | --- | --- |
| E-mail, anonymous SMTP and SMTP AUTH | Community | Passed with a local Mailpit. |
| Slack, Microsoft Teams, Rocket.Chat, DingTalk and Gotify webhooks | Community | Passed: each received valid JSON at a local capture listener. |
| Project **Allow alerts**, user **Send alerts**, template **Suppress success alerts** | Community | Passed. |
| **Send test notification** | Community | 204 and delivery when alerts are allowed; 409 when they are not. |
| Telegram, implicit-TLS e-mail | Community | Present in the source, not exercised. |
| Paid notification features | None | No licence check on any alert path. |

Sharp edges found:

- Failure e-mail goes to project members and to global administrators who
  ticked **Send alerts**, including an administrator outside the project; the
  **Test Alerts** button reaches members only. Successful tasks send no
  e-mail. Webhooks receive successes as well unless the template suppresses
  them. By the source, stopped tasks alert nobody; that case was not
  exercised.
- **A failed webhook delivery writes the webhook URL, and the Gotify token,
  into the task log.**
- A dead receiver does not change the task's result.

## Concurrency and task control

| Capability | Edition | Live result |
| --- | --- | --- |
| Global `max_parallel_tasks` | Community | Passed across projects; needs a restart; `0` means 9999. |
| Project limit | Community | Passed; applies without a restart; `0` means no limit. |
| Template **Allow parallel tasks** | Community | Passed. |
| Stop a running task, graceful or forced | Community | The task showed `stopped` within 0.1 s. |
| Stop a queued task | Community | See below. |
| Raw output and task statistics | Community | Passed. |
| Ansible task summary | Paid only | Answers 200 with no data. |

Sharp edges found:

- **Stopping a running task did not end all of its processes.** Three seconds
  after the task showed `stopped`, a worker `ansible-playbook` process and the
  command it was running were still alive and had to be killed by hand.
- **A force-stopped queued task still ran.** Stop then Force stop on a queued
  task showed `stopped` at once, but the playbook ran when the task was
  dequeued. A single plain Stop prevented the run.
- Enabling **Allow parallel tasks** does not release a run already queued
  behind a running one.
- Stopping a finished task rewrites its status to `stopped`.
- `max_task_duration_sec` did not stop a task running on the server itself.

## Identity and roles

Chapter: [identity, roles and credentials](../15-identity.md); appendix:
[OpenID Connect and LDAP](../appendices/identity-providers.md).

| Capability | Edition | Live result |
| --- | --- | --- |
| Four built-in project roles | Community | Passed; the permission matrix matched the source. |
| API tokens and roles | Community | A token acted with its user's current role; a demotion applied at once; revocation was immediate. |
| TOTP two-factor | Community | Passed, with the caveats below. |
| OpenID Connect | Community | Passed with Dex: new user, repeat login, logout. |
| LDAP | Community | Passed with lldap, with the caveats below. |
| E-mail one-time codes | Paid only | Stub. |
| Custom roles | Paid only | Stub (404). |
| Per-template permissions | Paid only in the UI | The API refused a manager's grant with 400, and the Guest could not run the template. |

Observed project permissions:

| Action | Owner | Manager | Task runner | Guest | Non-member |
| --- | --- | --- | --- | --- | --- |
| View templates, task output, Key Store names, team | yes | yes | yes | yes | 404 |
| Download the project backup | yes | yes | yes | yes | 404 |
| Run a task | yes | yes | yes | no | 404 |
| Edit templates, create keys | yes | yes | no | no | 404 |
| Change project settings, manage team, delete project | yes | no | no | no | 404 |

Sharp edges found:

- **Any project member, Guest included, can read another member's TOTP seed**
  through the project user API. Admins can read every seed.
- **API tokens bypass TOTP**, and a code can be used twice within its window.
- On PostgreSQL the enrolment request answered 400 although the TOTP was
  stored, and no recovery code reached the user.
- Setting `mfa.totp.enabled` to false silently removes the second factor from
  enrolled users.
- An OIDC e-mail equal to an existing local user's was refused, not linked.
- **LDAP does not verify the LDAPS certificate**: an untrusted self-signed
  certificate was accepted.
- **While the LDAP server was down, new password logins failed for everyone,
  the local admin included.** Existing sessions kept working. OIDC sign-in
  takes a separate path; it was not tested during the outage.
- A directory user with the same name as a local account locked that account
  out with both passwords.

## Task JWT and key rotation

Appendices: [task identity](../appendices/task-identity.md) and
[maintenance](../appendices/maintenance.md).

| Capability | Edition | Live result |
| --- | --- | --- |
| Task JWT (`jwt` block, per-template audience and TTL) | Community | Passed. JWKS answered 404 while disabled and one ES256 key when enabled; invalid TTL or audience settings were refused with 400. |
| OpenBao JWT login with the task token | Community (custom integration) | Passed: a role bound to the template's numeric `template_id` read its secret; another template was denied; a template with JWT off received no token. Bound claims written as strings, as in the pinned documentation's example, were refused. |
| Encryption keyring (`encryption.keys_file`) and `semaphore vault rekey` | Community | Passed: the new key was applied without a restart, rows moved to it, tasks decrypted credentials before and after, and the JWT signing key id did not change. |

Sharp edges found:

- `semaphore vault rekey --help` names the active pointer `active.access_key`;
  2.19.12 ignores that name and reads `active.secret_key`.

## History, audit and portability

Chapter: [schedules, notifications and task control](../16-semaphore-operations.md);
appendix: [maintenance](../appendices/maintenance.md).

| Capability | Edition | Live result |
| --- | --- | --- |
| Task history, output, raw output, statistics | Community | Passed. |
| Project activity log (events API) | Community | Passed for task runs, resource changes and membership; see below for what it omits. |
| syslog output (`syslog` block), default and RFC 5424 formats | Community | Passed: service messages reached the local syslog with the configured tag. |
| Activity and task log files (`log.events`, `log.tasks`) | Paid only | No files were written. |
| Retention (`max_tasks_per_template`) | Community | Passed: the newest three tasks were kept, older ones and their output were removed. |
| Task deletion | Community | Passed; administrators only. |
| Project backup and restore (API) and `semaphore project export`/`import` | Community | Passed, as configuration portability; see below. |

Sharp edges found:

- **The activity log is not an audit trail of access.** It records task runs,
  resource changes as text and membership changes without the new role. It
  records nothing for logins, user creation or deletion, integrations, task
  deletion, backup, restore or project deletion, and deleting a project
  deletes its events.
- `/api/events` shows only projects you are a member of, even to an
  administrator.
- **A project export omits Key Store values and variable-group secrets, but it
  is not free of credentials.** Restored Key Store entries came back empty: the
  first task on the restored project failed with
  `secret must be valid json in key 'Practice target SSH'`, and Ping succeeded
  once the keys were re-entered. The export did contain a webhook alias in
  plain text, and the source shows it can also carry other credential-bearing
  values. Keep exports private. Task history and events do not travel.
- A restore needs a project name that does not exist yet; a duplicate is
  refused with 400.
- The pinned source shows that populated template JWT settings and one-time
  schedule times are exported as `{}`. The test project had neither populated,
  so this was not exercised.
- Pruned and deleted tasks disappear, but their events remain.

## Runners

Chapter: [runners](../18-runners.md).

| Capability | Edition | Live result |
| --- | --- | --- |
| Global runner with a one-time registration token | Community | Passed: the token worked once and a replay was refused. |
| Runner to server over HTTPS with a pinned certificate | Community | Passed through the guide's `expose-semaphore.sh --mode https`. |
| Remote execution (`use_remote_runner`) | Community | Passed: with the controller blocked from the target's SSH port, a controller-local Ping failed and the same Ping on the runner succeeded. |
| Runner status, offline runner, disabled runner | Community | Passed: a task waited for an offline runner and ran when it returned; a disabled runner made the task fail at once. |
| Shared `runner_registration_token` | Community | Passed; it creates an inactive, non-default runner. |
| `semaphore runner unregister` | Community | Failed in 2.19.12: the server answered 401 and the command panicked. |
| Project runners | Paid only | Stub. |
| Runner tags | Paid only in the UI | The API accepted tags without a licence check; the UI hides them. Not recommended. |

Sharp edges found:

- If the runner cannot read the certificate file named in
  `server_ca_cert_file`, it silently uses the system trust store instead, and
  so refuses a self-signed server with a certificate error.
- The runner ran on the target host itself for this test. A separate runner
  host is the design the chapter recommends.

## Upgrade and rollback drill

Appendix: [maintenance](../appendices/maintenance.md).

The drill quiesced the server, took chapter 10's capture (which verified),
stopped Semaphore, undid the database migrations with
`semaphore migrate --undo-to`, ran Community 2.18.30, then returned to 2.19.12.

| Step | Result |
| --- | --- |
| `--undo-to 2.18`, then to the exact 2.18 target | Both exited 0 and the migrations table matched. A `v`-prefixed version and combined flags were refused before any change. |
| Community 2.18.30 on the downgraded database | It started, applied its own migration, and login, projects and templates worked. **The tested Ping failed** while decrypting its inventory credentials, with `illegal base64 data`: 2.18 cannot decode the key-id envelope 2.19 stores Key Store secrets in. |
| Back to 2.19.12 | The migrations were applied again, the schema matched the starting schema, no rows were lost, readiness passed and Ping succeeded. The measured stop-to-return interval of the version switch was 18 seconds, excluding the capture and the final checks. |

Conclusion: `--undo-to` with an older binary is not a working rollback from
2.19. Test an upgrade on a restored copy first, and roll back by restoring the
capture.
