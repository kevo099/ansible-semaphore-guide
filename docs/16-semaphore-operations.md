# 16. Schedules, notifications and task control

[Previous: identity and credentials](15-identity.md) · [Next: API and integrations](17-api-and-integrations.md) · [Coverage](COMMUNITY-COVERAGE.md)

## Goal

Schedule a qualified playbook, understand why tasks wait, and verify alerts and
task output. Leave no recurring practice work behind.

| Edition and evidence | Scope |
| --- | --- |
| Edition | Community 2.19.12 |
| Tested with | ansible-core 2.21.4; RHEL 9.8 controller and Ubuntu 24.04 target |
| UI or API path | Schedule, Task Templates, project settings; `/api/project/PROJECT_ID/schedules` and `/tasks`; live API tests, UI labels checked against pinned source |
| Evidence | [Schedules](validation/2026-09-community.md#schedules), [notifications](validation/2026-09-community.md#notifications), [task control](validation/2026-09-community.md#concurrency-and-task-control), [history](validation/2026-09-community.md#history-audit-and-portability) |
| Known limits | Stop can leave processes alive; forced queued tasks can still execute; task summaries are paid only; the activity log records no logins or administration |

## Do: establish an operating baseline

Prerequisites: finish [chapter 6](06-semaphore.md), have project Owner access,
and use its working Ping template with an explicit target Limit. These exercises
create schedules and tasks.

**Where: browser, as the project Owner.** Run Ping manually. Read the complete
target recap, checking identity, `changed=0` and no failures. Record its ref,
inventory, credentials and Limit.

Schedules use `schedule.timezone`, default **UTC**, not the server's local zone.
The environment setting is `SEMAPHORE_SCHEDULE_TIMEZONE`. It is read at startup:
restart after changing it. `GET /api/info` reports `schedule_timezone`; use
[chapter 17](17-api-and-integrations.md) for API access. Keep UTC for this
exercise and compare dispatch times in UTC.

## Do: create a one-time schedule

**Where: browser, as the project Owner.** Open **Schedule → New Schedule → Run
once**. Name it **Operations ping once**, select the Ping **Template**, leave
**Enabled** on, and choose **Run at** a few minutes ahead in the schedule
timezone. Leave **Delete after run** off. Read **Next run time**, then save.

For API clients, the type is `"run_at"`; `run_at` must be a future timestamp.
**Send UTC ending in `Z`.** The tested PostgreSQL setup dropped supplied
offsets: `+05:45` became 5 hours 45 minutes late, and `-04:00` became four hours
early. That early entry was already past and became inactive. The pinned UI
source converts its input to UTC first.

## Check: verify the scheduled run

Compare the new task's creation/start times with the requested time; queueing
can delay execution. Confirm the intended target recap and one execution. The
tested one-time entry became inactive after firing. Delete only **Operations
ping once** when its task finishes.

Repeat with **Delete after run** checked. The schedule disappeared in the test
while its task record remained, with API `schedule_id` null. Deletion does not
prove the task finished.

## Do: create and stop a recurring schedule

**Where: browser, as the project Owner.** Create **Operations ping minute** using
**Schedule → New Schedule → Cron**, the same Ping template and **Enabled**.
Select **Show cron format** and enter `* * * * *` in **Cron**. Observe two minute
boundaries and their task recaps. Edit this entry, clear **Enabled**, and save.
Check that the next two boundaries create no new tasks; let existing tasks finish,
then delete only this schedule. Re-enabling an ordinary cron schedule resumes it.

| Cron input | Evidence in this guide |
| --- | --- |
| `* * * * *` | Ran at minute boundaries; standard five-field syntax |
| `@every 20s` | Created three tasks 20 seconds apart |
| `@hourly` | Validation accepted it; an hour-long execution check was not tested |
| `CRON_TZ=Asia/Kathmandu * * * * *` | Per-schedule timezone prefix supported; timed checks used hour/minute expressions in this zone |
| Four or six fields; minute `61` | Validation rejected them |

`CRON_TZ=Zone` overrides the configured zone for that expression. Tests
confirmed the process zone did not select the scheduler's default zone. Validate
API input with `POST /api/project/PROJECT_ID/schedules/validate` and
`{"cron_format":"* * * * *"}`. Acceptance proves syntax; verify dispatch
separately.

## Concept: schedule parameters and edits

For cron API objects, omit `type` or use `""`; `"cron"` is invalid. Set `active`
explicitly: omitting it stores false. Schedules carry task parameters including
messages, extra variables and Ansible run options. This is a fragment, not a
complete request:

```json
{
  "task_params": {
    "message": "Operations schedule practice",
    "environment": "{\"practice_marker\":\"schedule\"}",
    "params": {"dry_run": true, "diff": true}
  }
}
```

Tests verified parameters in task output. An allowed tag override worked; a
disallowed Limit override was ignored. Keep the fixed Ping Limit; see [inputs
and templates](14-inputs-and-templates.md).

**A schedule PUT replaces omitted fields.** The test omitted `active` and
`task_params`; they became false and null. GET the **individual** schedule, edit
that complete object, and PUT it back with matching IDs. The project schedule
list omits task parameters, so it is not a safe replacement body. For an ordinary
schedule toggle alone, PUT `{"active":false}` to
`/api/project/PROJECT_ID/schedules/SCHEDULE_ID/active`.

## Do: poll a practice repository

Prerequisites: a separate practice Git branch, a qualified harmless template,
and a repository credential that can read it. This creates a commit checker.
**Where: browser, as the project Owner.** Edit that practice template and enable
**Auto-run task if new git commit have been found**. Select its **Repository**
and polling interval (the English field reads **checkInterval**), then save.

This polls with `git ls-remote`; it is not a webhook. The first poll runs
without a new commit. In the test, an unchanged poll launched nothing; a changed
ref launched a successful task. Editing without a new commit launched again
because the edit resets the remembered hash.

**The inactive flag does not stop this poller.** The test saved `active:false`,
made another commit, and observed a task start on the next poll. For cleanup,
clear the template's checkbox and save to delete its checker; let dispatched
tasks finish. The project Schedule list does not list commit checkers. API clients
find them at `/api/project/PROJECT_ID/templates/TEMPLATE_ID/schedules`.

## Concept: three concurrency limits

Keep the guide's global limit of one while learning. Parallel tasks can change
the same target at once; a template flag does not provide target locking.

| Gate | Setting and effect in 2.19.12 |
| --- | --- |
| Whole server | `max_parallel_tasks` / `SEMAPHORE_MAX_PARALLEL_TASKS` counts all projects; changing it needs a restart. `0` loads as **9999**, not zero permitted tasks. |
| Project | **Max number of parallel tasks (Optional)**, API `max_parallel_tasks`; applies on the next dispatch check without restart. `0` means no project limit. |
| Template | **Allow parallel tasks**, API `allow_parallel_tasks`; off serializes runs of that template. Other limits still apply when it is on. |

The source shows that enabling the template flag while its first task runs does
**not** release a run already queued behind it: the running task keeps its
earlier template copy. The live test enabled the flag before submitting a second
run, which still waited. Overlap checks used playbook begin/end output and task
times.

`max_task_duration_sec` is **not enforced for tasks executed on the server itself**:
a 30-second local task succeeded with a 15-second setting. The pinned source only
enforces that timeout in remote runner jobs; see [runners](18-runners.md).

## Do: observe a queue

Prerequisites: the repository you used in [chapter 14](14-inputs-and-templates.md),
no other tasks running, and global limit one. This creates an **Operations
local** inventory and an **Operations pause** template that uses the guide's
[`examples/semaphore/operations-pause.yml`](../examples/semaphore/operations-pause.yml).
It prints a begin marker, waits 40 seconds on the controller and prints an end
marker; it changes nothing. On the seeded Enterprise Linux controller, copy it
into the lab folder as its owner, as chapter 14 does for its demo:

```bash
mkdir -p /opt/ansible-lab/examples
cp examples/semaphore/operations-pause.yml examples/semaphore/operations-failure.yml \
  /opt/ansible-lab/examples/
find /opt/ansible-lab ! -group semaphore
```

**Where: browser, as the project Owner.** Create the static **Operations local**
inventory with **None** credentials and this content:

```text
localhost ansible_connection=local ansible_python_interpreter="{{ ansible_playbook_python }}"
```

Create **Operations pause**, selecting that inventory, the repository and the
playbook path. Leave **Allow parallel tasks** off. This deliberately
runs on the controller, unlike the target Ping lesson. Run it twice promptly.
Confirm one runs while the other waits. Let both finish and read both begin/end
markers before any cancellation practice.

## Check: stop without trusting the badge

Run the pause task twice again. Click **Stop** once on the **queued** task. It
remains `stopping` until dequeued, then becomes `stopped` without running.
Verify it has no begin/end markers.

**Do not follow Stop with Force Stop on a queued task.** Both that UI sequence
and a direct forced API stop marked it `stopped` immediately in the tests, but
the playbook still ran when dequeued. Its log had begin/end markers and a recap
even though its recorded start time was null. A single ordinary Stop prevented it.

For a running task, **Stop is not a kill of everything**. With ordinary and
forced stops, an `ansible-playbook` worker and its `sleep` were alive three
seconds after the task showed `stopped`.

**Where: controller, as root.** Inspect stopped local tasks; keep command-line
output private:

```bash
pgrep -u semaphore -fa ansible-playbook
ps -u semaphore -o pid,ppid,pgid,etime,args --forest
```

Match commands, parent/child PIDs and elapsed times to your stopped task. End
only verified leftovers with `kill -TERM -- PID`, substituting each child and
worker PID; recheck and use `kill -KILL -- PID` only if it remains. Do not kill
every Semaphore process. Check targets separately: stopped work may have changed
them; terminating a controller process is not rollback.

Stopping a **finished** task through the API rewrote its success status to
`stopped`, retaining its times. Do not use stop requests as history cleanup.
Keep the practice objects for the alert exercise; if skipping it, remove only
those objects and the pause playbook after all runs end.

## Do: deliver a practice notification

Prerequisites: the local practice inventory/repository above and a test SMTP
receiver you control. Save current alert settings privately for restoration.
This adds **Operations failure**, its playbook and optionally one Mailpit
container. The rest of this chapter needs no container runtime.

**Where: controller, as root.** Optional fixture: with Podman already installed
and ports 1025/8025 unused, start the tested Mailpit v1.31.3 digest on loopback:

```bash
podman run -d --name practice-mailpit --network host --read-only \
  --cap-drop=ALL --security-opt no-new-privileges --memory 256m --no-healthcheck \
  docker.io/axllent/mailpit@sha256:ed9b00c609e77e99c79b93f1178255ebc271868920f2c69a8d166bd5634ed10d \
  --smtp 127.0.0.1:1025 --listen 127.0.0.1:8025 \
  --smtp-disable-rdns --disable-version-check \
  --smtp-auth-accept-any --smtp-auth-allow-insecure --tags-username
curl --fail --retry 10 --retry-connrefused --retry-delay 1 --max-time 2 \
  http://127.0.0.1:8025/readyz
```

As root, merge these fields into `/etc/semaphore/config.json` with an editor;
do not replace the whole file, and keep it `root:semaphore` mode 0640.
`email_port` is a string. Wait for the queue and workers to finish, then run
`systemctl restart semaphore` to load the settings.

```json
{
  "email_alert": true,
  "email_host": "127.0.0.1",
  "email_port": "1025",
  "email_sender": "semaphore@example.test",
  "email_secure": false,
  "email_tls": false
}
```

**Where: workstation, as your SSH administrator.** For Mailpit, forward loopback
port 8025 using the [private
tunnel](appendices/browser-access.md#private-tunnel) pattern; open its web
interface.

**Where: browser, as the project Owner.** Enable **Allow alerts for this
project** (API `alert`) and **Save**. Save your account's e-mail address and
**Send alerts** choice, then press **Test Alerts** in project settings. Check
the receiver. Project alerts off returned 409; 204 alone does not establish
delivery. The subject says “failed” despite a synthetic success task. This test
only addresses opted-in project members.

The failure exercise uses
[`examples/semaphore/operations-failure.yml`](../examples/semaphore/operations-failure.yml),
which fails on purpose on the controller.

## Check: recipients and delivery

**Where: browser, as the project Owner.** Create **Operations failure** using
that playbook, the same repository and **Operations local**. Run it, then
**Operations pause**. Inspect task results and receiver contents independently.

Normal task e-mail is **failure-only**, gated by **Send alerts**. Tests
delivered to an opted-in **global administrator outside the project** and an
opted-in member; an opted-out member got nothing. The source merges members and
global admins for real tasks. Do not assume the test button's member-only
recipient list is the real failure recipient list.

Webhooks received success and failure. **Suppress success notifications** on the
template (API `suppress_success_alerts`) silenced success but preserved failure.
The pinned source excludes stopped tasks from all alerts; that case was not tested.

| Transport | Server configuration fields | Evidence boundary |
| --- | --- | --- |
| E-mail | Fields above; `email_username`, `email_password` for AUTH | Anonymous SMTP and AUTH captured locally; AUTH used `email_secure:true`, `email_tls:false` on loopback |
| Slack | `slack_alert`, `slack_url` | Local JSON capture, success and failure |
| Microsoft Teams | `microsoft_teams_alert`, `microsoft_teams_url` | Local JSON capture; response 202 accepted |
| Rocket.Chat | `rocketchat_alert`, `rocketchat_url` | Local JSON capture, success and failure |
| DingTalk | `dingtalk_alert`, `dingtalk_url` | Local JSON capture, success and failure |
| Gotify | `gotify_alert`, `gotify_url`, `gotify_token` | Local JSON capture, success and failure |
| Telegram / implicit-TLS e-mail | Present in pinned source | Not tested; no setup recipe here |

Local captures prove payloads, not real SaaS delivery. Enter credentials
privately into protected configuration, keeping them out of commands and
history. In this source `email_secure:true` with `email_tls:true` selects
implicit TLS, not STARTTLS. Do not infer security from option names.

**Treat task logs as sensitive once alerts are enabled.** Connection failures
printed complete webhook URLs and the Gotify token into task output. A dead
webhook receiver left the task result unchanged; e-mail still arrived. Check
receiver evidence and delivery errors before declaring success.

Cleanup: restore only the alert settings you changed, including user/project/
template flags. **Where: controller, as root.** After tasks finish, restore the
prior SMTP configuration, restart Semaphore, and, if created here, remove only
the fixture with `podman rm -f practice-mailpit`. **Where: browser, as the project
Owner.** Delete the two Operations templates and Operations local inventory.
If you copied the example playbooks into the lab folder, remove them as its
owner. Close the Mailpit tunnel.

## Check: read task history and the activity log

Use a completed Ping task from [chapter 6](06-semaphore.md); this check creates
no objects. Task history and events work in Community 2.19.12.
The [live evidence](validation/2026-09-community.md#history-audit-and-portability)
checked their APIs; the UI labels below come from the pinned 2.19.12 source,
not a browser test of this procedure.

**Where: browser, as a member of the practice project.**

1. Open **Dashboard → History** and select the completed task's number.
   Match its template, **User**, **Start** and **Duration** to your run.
2. Read **Log** through the full target recap. Ping should identify the
   intended target with `changed=0`, `unreachable=0` and `failed=0`.
3. Open **Details**. Compare the run's inputs with your intended scope;
   **Commit info** appears only when the task has a recorded commit hash.
   Do not treat a missing hash as proof of the repository revision.
4. Open **Raw log** if you need plain text, and review it privately before
   sharing. The tested raw-output API removed ANSI formatting codes.
5. Return to **Dashboard → Activity** and match the task number, user and time.

The tested Ping wrote three activity entries: `WAITING`, `STARTING` and
`finished with status SUCCESS`. A failed task ended with `ERROR`. These are
task lifecycle descriptions; they do not replace reading the play's output.

| Activity in 2.19.12 | What the evidence showed |
| --- | --- |
| Resource edits | Description text, such as a template being updated; no before/after field values. |
| Membership changes | Added, removed or role changed; the new role is not recorded. |
| Login, user creation/deletion, integrations | No activity event. |
| Task deletion, project export/import, project deletion | No activity event. |
| Deleted project | Its existing events disappear too. |

**The activity log is not an audit trail of logins or administration in
2.19.12.** The global `/api/events` feed is membership-filtered even for an
administrator: it does not collect every project's events for that account.
Project members, including Guests, can read their project's events and output.
See [API access](17-api-and-integrations.md) for authenticated API requests.

Task reads use `/api/project/PROJECT_ID/tasks/TASK_ID`; append `/output` for
JSON lines or `/raw_output` for plain text. Project activity uses
`/api/project/PROJECT_ID/events`, or `/events/last` for the newest 200 events.
An old event can refer to a task whose record and output have been pruned;
the tested reads then returned HTTP 400. See
[retention and deletion](appendices/maintenance.md) before removing history.

The task **Summary** and structured Ansible host/error features are paid only.
The `log.events` and `log.tasks` file exporters are also paid only: enabling
them in Community wrote no files. Ordinary service logging is separate.

## Check: read task output through the API

**Where: browser, as a project member.** Read a completed task's full output.
Match its ID, timestamps, begin/end markers and recap. Use [chapter
17](17-api-and-integrations.md) for these API reads:

| Path after `/api/project/PROJECT_ID` | What it returned |
| --- | --- |
| `/tasks/TASK_ID/raw_output` | Plain text with ANSI colour codes removed; matched the output rows |
| `/tasks/TASK_ID/output` | JSON rows including output text, task ID and time |
| `/stats`, `/templates/TEMPLATE_ID/stats` | Daily counts by status; `avg_duration` remained zero |

The Community **task summary** endpoints returned empty/null data; task
summaries are **paid only**, separate from working raw-output and stats reads.
The pinned stats implementation does not populate `avg_duration`; zero is not
measured instant execution. These reads create no objects.

## Do: send service logs to syslog

This optional exercise uses the controller's existing local syslog socket.
The campaign verified receipt through `/dev/log`, including a successful Ping's
queue/start messages. Remote syslog forwarding was not tested.

**Where: controller, as root.**

First pause schedules, wait for the task pool to empty and take
[chapter 10's capture](10-recovery.md). Keep the existing `syslog` setting in
that protected recovery set. This exercise changes only that setting and
creates two Ping tasks. Check the local socket before changing configuration:

```bash
test -S /dev/log
```

Merge this member into `/etc/semaphore/config.json`; retain its other members:

```json
{"syslog": {"enabled": true, "tag": "semaphore-practice"}}
```

Leave `network` and `address` unset to use the local socket. The pinned source
shows that a connection failure prevents service startup. Restart Semaphore:

```bash
systemctl restart semaphore
```

**Where: browser, then controller as root.** Run the qualified Ping template,
check its full recap, then prove the messages arrived through syslog:

```bash
journalctl _TRANSPORT=syslog SYSLOG_IDENTIFIER=semaphore-practice --since '5 minutes ago' --no-pager
```

Match `Task added to queue` and `Task started` to that task's ID. The optional
`"format": "rfc5424"` setting also delivered a startup message in the test;
it does not add missing activity events. To clean up, restore only the prior
`syslog` setting, restart, qualify Ping again and resume your paused schedules.
