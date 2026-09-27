# Appendix: other task apps

[Back to inputs and templates](../14-inputs-and-templates.md) · [Coverage](../COMMUNITY-COVERAGE.md)

## Goal

Run harmless scripts and a local-only OpenTofu resource; inspect inputs, exit status and confirmation.

| Edition and evidence | Scope |
| --- | --- |
| Edition | Community 2.19.12 |
| Tested with | RHEL 9.8 controller; Python 3.12.14; OpenTofu 1.12.6; Terragrunt 1.1.6 |
| UI or API path | API-created templates and launches; UI labels below checked against the pinned source, not a browser rehearsal |
| Evidence | [Other task apps](../validation/2026-09-community.md#other-task-apps) |
| Known limits | Local execution and local state only; no cloud account; Terraform and PowerShell not tested |

Prerequisites: complete [the first job](../06-semaphore.md), use an isolated practice
project and service-readable local-folder repository, and understand
[authenticated API requests](../17-api-and-integrations.md). Substitute your repository
root for `/opt/ansible-lab`. Create only the `app-practice` files, two variable groups,
three templates and one state directory described here. Keep concurrent runs off:
the pinned Terraform-family runner passes `-lock=false`.

## Do: check the runtime

**Where: controller, as root.**

1. Inspect the service's `PATH`: the guide uses `/opt/ansible-venv/bin:/usr/local/bin:/usr/bin:/bin`.
2. Ensure `bash` and `python3` exist there. Install OpenTofu **1.12.6** for local state.
   Terragrunt **1.1.6** is optional. These are campaign pins, not the latest-version claims.
3. For Linux amd64, verify downloads before installing them in `/usr/local/bin`:

| Binary | Release asset | SHA-256 of the asset |
| --- | --- | --- |
| OpenTofu 1.12.6 | [tofu_1.12.6_linux_amd64.tar.gz](https://github.com/opentofu/opentofu/releases/download/v1.12.6/tofu_1.12.6_linux_amd64.tar.gz) | `50a6106fa4de523d09c87af85f3db1dd47535fc005727fdca6852146476b88ec` |
| Terragrunt 1.1.6 | [terragrunt_linux_amd64](https://github.com/gruntwork-io/terragrunt/releases/download/v1.1.6/terragrunt_linux_amd64) | `d75a80bb264758ba00dabcb17f4b507fcdab4ca90d9e41f96750df036bf69b04` |

The 2.19.12 source auto-detects Ansible, Bash, Terraform, OpenTofu and Terragrunt on
the service `PATH` at startup, unless the app already has an explicit configuration
entry. Python needs `apps.python.active:true` to appear in **New template**, even
when `python3` exists. Edit `/etc/semaphore/config.json` privately. Set only the
nested `apps.python.active` field to the JSON boolean `true`, creating those
objects if absent. Preserve every other setting, including any Python path.

Wait for existing tasks to finish, restart, and check runtime versions below.
The `cd /` matters: the service account cannot read root's working directory,
and `tofu` refuses to start without one.
If `apps.python.path` is set, also check that configured executable's version.

```bash
systemctl restart semaphore
systemctl is-active semaphore
sudo -u semaphore env PATH=/opt/ansible-venv/bin:/usr/local/bin:/usr/bin:/bin \
  bash -c 'cd / && command -v bash python3 tofu && python3 --version && tofu --version'
```

**Where: browser, as the practice project administrator.**

Check **Task Templates → New template** for **Bash Script**, **Python Script** and
**OpenTofu Code**. The `active` flag filters this menu, not execution permission:
the API accepted a Python template while it was inactive.

## Do: run Bash and Python

**Where: controller, as the lab folder's owner.**

Create these files in your local repository. They print only an ordinary
marker. Plain `mkdir` keeps the folder's `semaphore` group, as
[3b explains](../03-controller-el9.md#do-give-the-templates-the-targets-sudo-password).

```bash
mkdir -p /opt/ansible-lab/app-practice/tofu
cat > /opt/ansible-lab/app-practice/marker.sh <<'BASH'
#!/usr/bin/env bash
set -eu
printf 'Bash marker=%s\n' "${APP_MARKER:-unset}"
case "${APP_EXIT:-0}" in
  0) exit 0 ;;
  3) exit 3 ;;
  *) printf 'APP_EXIT must be 0 or 3\n' >&2; exit 2 ;;
esac
BASH
cat > /opt/ansible-lab/app-practice/marker.py <<'PY'
import os
import sys
print("Python marker=" + os.environ.get("APP_MARKER", "unset"))
code = os.environ.get("APP_EXIT", "0")
if code not in ("0", "3"):
    raise SystemExit("APP_EXIT must be 0 or 3")
sys.exit(int(code))
PY
chmod 0640 /opt/ansible-lab/app-practice/marker.sh \
  /opt/ansible-lab/app-practice/marker.py
find /opt/ansible-lab ! -group semaphore
```

The `find` must print nothing.

**Where: browser, as the practice project administrator.**

Create **Variable Groups → New Group**, named **App practice scripts**.
Keep **Extra variables** as `{}`. In **Environment variables**, enter:

```json
{"APP_MARKER":"practice marker","APP_EXIT":"0"}
```

Create **App practice Bash** using **Bash Script**, and **App practice Python** using
**Python Script**. Select the local repository and **App practice scripts**. Set
**Script Filename \*** to `app-practice/marker.sh` or `app-practice/marker.py`.
Keep **CLI args** empty and launch each. Change `APP_EXIT` to `"3"`, rerun, then restore `"0"`.

## Check: inputs and exit status

Expect the chosen marker in each log: `APP_EXIT=0` gives `success`; `APP_EXIT=3`
gives `error` and `exit status 3`. The campaign observed Python's zero/nonzero pair
and Bash's success; Bash's nonzero behavior comes from the shared runner source.
These smaller teaching scripts were not the exact campaign probe files.

The live Bash/Python probes and `ShellApp` source establish this input contract:

| Input | What reaches the script |
| --- | --- |
| Script path | `bash SCRIPT` or `python3 SCRIPT`, resolved from the repository working directory |
| Variable-group **Extra variables** JSON | Use string values: separate `name=value` arguments, not a JSON document on stdin |
| Variable-group secret with type `var` | A `name=value` argument before template arguments |
| Template **CLI args** | Arguments after secret vars and before ordinary extra variables |
| Task **CLI args** | Appended last, only when the template permits the override |
| Variable-group ENV and secret type `env` | Process environment variables |
| Survey target `env` | Process environment instead of an ordinary argument; demonstrated with Bash and Python's exit-code survey |
| Task identity details | Selected `SEMAPHORE_TASK_DETAILS_*` environment variables |
| Standard input | Empty; observed by Bash and shown for both apps by the shared source |

Do not depend on JSON key order. Do not print secret arguments or environment
values: the probes hid their own values, so their logs do not prove masking.
Shell scripts have no Ansible `no_log`; the script must prevent disclosure itself.

## Do: keep OpenTofu state local

Built-in `terraform_data` needs no downloaded provider or cloud credential.
Keep state and runtime data outside the repository, under `/var/lib/semaphore`,
where the hardened guide service can write.

**Where: controller, as root.**

```bash
install -d -o semaphore -g semaphore -m 0700 /var/lib/semaphore/app-practice
```

**Where: controller, as the lab folder's owner.**

```bash
cat > /opt/ansible-lab/app-practice/tofu/main.tf <<'HCL'
terraform {
  backend "local" {
    path = "/var/lib/semaphore/app-practice/terraform.tfstate"
  }
}
variable "message" {
  type = string
}
resource "terraform_data" "practice" {
  input = var.message
}
output "message" {
  value = terraform_data.practice.output
}
HCL
chmod 0640 /opt/ansible-lab/app-practice/tofu/main.tf
```

**Where: browser, as the practice project administrator.**

Create **App practice tofu** in **Variable Groups**. Set **Extra variables** to
`{"message":"first marker"}` and **Environment variables** to:

```json
{"TF_DATA_DIR":"/var/lib/semaphore/app-practice/.terraform","TF_IN_AUTOMATION":"1"}
```

**Where: workstation, using your authenticated practice-project API client.**

Create with `POST /api/project/PROJECT_ID/templates`. Replace each quoted uppercase
ID placeholder below with its numeric ID. `arguments` is a JSON-encoded string.
Preserve `"default":[]`: with only `init`, ordinary variable and destroy arguments are omitted.

```json
{
  "project_id": "PROJECT_ID",
  "name": "App practice OpenTofu",
  "app": "tofu",
  "playbook": "app-practice/tofu",
  "repository_id": "REPOSITORY_ID",
  "environment_ids": ["GROUP_ID"],
  "arguments": "{\"init\":[\"-lockfile=readonly\"],\"default\":[]}",
  "task_params": {"allow_auto_approve": true, "allow_destroy": false}
}
```

The API creates a default workspace inventory; record its id for cleanup.
**Allow destroy** is not an enforcement boundary: destroy succeeded with `allow_destroy:false`.

## Check: plan, confirm and destroy

Launch with `POST /api/project/PROJECT_ID/tasks`; use this body after replacing
the template id. Poll `GET /api/project/PROJECT_ID/tasks/TASK_ID` and read its log.

```json
{"template_id":"TEMPLATE_ID","params":{}}
```

Expect one planned addition, then `waiting_confirmation`. Review it and `POST` `{}`
to `/api/project/PROJECT_ID/tasks/TASK_ID/confirm`. The observed run continued to apply.
**Confirm** in the pinned UI's task log uses this endpoint. This is a pause between
plan and apply, not an approval system with separate approvers. The campaign used
its administrator; it did not test an approver-role matrix.

Set the group's `message` before each changed run; send the listed `params` in the launch body.

| Run | `params` | Action and independently checked result |
| --- | --- | --- |
| Repeat unchanged | `{}` | No changes; success without confirmation; state unchanged |
| Set `message` to `rejected marker` | `{}` | At the pause, POST `{}` to the task's `/reject`; task ends `error`, state unchanged |
| Keep that changed value | `{"plan":true}` | Plan only; success without applying; state unchanged |
| Set `message` to `applied marker` | `{"auto_approve":true}` | Applies without pausing because the template allows it; output changes |
| Destroy this fixture | `{"destroy":true}` | Review the destruction plan, confirm, and check resources and outputs are empty |

**Where: controller, as root.** Independently inspect this exercise's state
after the first apply, rejected/plan-only runs, auto-approved change and destroy:

```bash
python3 - <<'PY'
import json
with open('/var/lib/semaphore/app-practice/terraform.tfstate') as stream:
    state = json.load(stream)
print("resources:", [r["type"] + "." + r["name"] for r in state.get("resources", [])])
print("outputs:", {k: v["value"] for k, v in state.get("outputs", {}).items()})
PY
```

## Concept: app and edition boundaries

| App or feature | Edition and tested status in 2.19.12 |
| --- | --- |
| Ansible | Works in Community; lesson qualification covered separately in [chapter 6](../06-semaphore.md) |
| Bash / Python | Works in Community; actual input delivery and Python failure observed |
| OpenTofu | Works in Community; plan, confirm/apply, reject, no-change, plan-only, auto-approve and destroy observed |
| Terragrunt | Works in Community; **plan only**, via OpenTofu; apply/destroy not tested |
| Terraform | Community runner exists in source; **not tested**, binary not installed |
| PowerShell | Community shell runner exists in source; **not tested**, binary not installed |
| Pulumi | **Not present** as a supported integration; template rejected with HTTP 400, `invalid app: pulumi` |
| Semaphore-managed Terraform state / task-stage summaries | **Paid Pro**; Community returned no states/stages and state-alias creation returned 404 |

Terragrunt 1.1.6's plan used `--tf-path=tofu` in both `init` and `default` argument
lists, plus `-lockfile=readonly` for `init`. HCL `inputs` reached OpenTofu. Semaphore
logged unsupported workspaces and skipped workspace selection. Only this plan was
tested. [Chapter 14](../14-inputs-and-templates.md) covers Build/Deploy types;
Workflows remain paid Pro.

## Do: clean up

**Where: browser or authenticated API client, as the practice project administrator.**

After destroy and the empty-state check, wait for all exercise tasks to finish.
Delete the three **App practice** templates, their automatically created workspace
inventory, and the two exercise variable groups. Keep the pre-existing repository.

**Where: controller.** As the lab folder's owner, remove
`/opt/ansible-lab/app-practice`; as root, remove
`/var/lib/semaphore/app-practice`. Restore the previous `apps.python` setting if changed
for this exercise, then restart with no active tasks. Remove optional binaries only
if installed for this exercise and unused elsewhere. The campaign retained binaries,
removed its state and exercise objects, and verified no tasks remained running.
