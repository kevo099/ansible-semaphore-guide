# 14. Inputs and templates

[Previous: Semaphore](06-semaphore.md) · [Next: identity and credentials](15-identity.md) · [Coverage](COMMUNITY-COVERAGE.md)

## Goal

Give a reviewed playbook predictable inputs. Attach variable groups, collect a
small survey, and check which launch controls the template actually permits.

| Edition and evidence | Scope |
| --- | --- |
| Edition | Community 2.19.12 |
| Tested with | ansible-core 2.21.4; RHEL 9.8 controller and Ubuntu 24.04 inventory target |
| UI or API path | **Variable Groups**, **Task Templates**; API `environment`, `templates`, `tasks` under a project |
| Evidence | [Inputs and templates](validation/2026-09-community.md#inputs-and-templates); [other task apps](validation/2026-09-community.md#other-task-apps) |
| Known limits | Survey validation is in the UI; values can execute Jinja; printed secrets are not masked; disabled overrides can be silently ignored. |

The campaign launched tasks through the API, including requests shaped like
the Run dialog. UI labels and validation rules below come from the pinned
2.19.12 source; this is not a claim of a complete browser walkthrough.

Prerequisites: finish [chapter 6](06-semaphore.md) and keep its working
inventory and credentials. This exercise creates two variable groups and one
task template. Use the `Inputs demo` names so cleanup can identify only these
objects.

## Do: choose the demo playbook

The guide ships a harmless playbook for this chapter,
[`examples/semaphore/input-demo.yml`](../examples/semaphore/input-demo.yml).
It asserts that its inputs have allowed values, then prints them as markers;
it changes nothing on the target. Point the template at a repository that
contains it: this guide's repository at a release tag that includes it, as
chapter 6 does for the lessons, or your own copy. On the seeded Enterprise
Linux controller, copy it into the lab folder as its owner:

```bash
mkdir -p /opt/ansible-lab/examples
cp examples/semaphore/input-demo.yml /opt/ansible-lab/examples/
find /opt/ansible-lab ! -group semaphore
```

The `find` must print nothing; see
[3b's group rule](03-controller-el9.md#do-give-the-templates-the-targets-sudo-password).

Assertions check the playbook's allowed values, including inputs supplied by
an API caller. They are not a sandbox for hostile Jinja: Ansible can evaluate
an input while checking it. Give launch access only to people you trust with
the playbook's execution context.

## Do: attach variable groups

**Where: browser, as a project administrator.**

Open **Variable Groups → New Group** (API resource: `environment`). Create
**Inputs demo first**. Under **Variables → Extra variables → JSON**, enter:

```json
{
  "demo_marker": "first",
  "demo_enabled": true,
  "demo_colour": "blue",
  "demo_count": 2
}
```

Under **Environment variables**, add `DEMO_MODE` with the value `first`.
Create **Inputs demo second** afterwards, with these extra variables:

```json
{"demo_marker": "second"}
```

Give the second group an environment variable `DEMO_MODE` with value `second`.
These deliberate duplicates make precedence visible. In ordinary templates,
prefer unique keys across groups.

Use **Task Templates → New template → Ansible Playbook** to create **Inputs
demo**. Select the repository and the playbook path from the previous step
(`examples/semaphore/input-demo.yml`, or `examples/input-demo.yml` in the lab
folder), the
working inventory from chapter 6, and both **Variable Groups**. Set **Ansible
options → Limit** to one inventory alias, such as `lab-ubuntu`. Leave **CLI
args** empty and check boxes under **Prompts** and **Ansible prompts** off.

Several groups can be attached. The template API field is `environment_ids`;
the singular `environment_id` still works but is deprecated. **Merge order is
by group ID, not the order you select or submit the groups.** In the tested
SQL-backed installation, the later-created group won duplicate JSON keys,
environment variables and secrets with the same name and type. Reversing the
submitted list did not reverse the result.

## Check: inspect the resolved inputs

Run **Inputs demo**, then read its complete output. Expect marker `second`,
mode `second`, colour `blue`, count `2`, a true boolean, and only the selected
inventory alias. The campaign verified precedence from values reported by the
play, including an integer and a dictionary, not from a green badge alone.

If you retain duplicate keys, inspect the group's IDs and rerun a harmless
probe after changing attachments. Do not use drag order as a precedence rule.
Ansible extra variables and process environment variables are separate:
`demo_marker` is an Ansible variable; `DEMO_MODE` is read with an environment
lookup on the execution machine. It is not automatically a target environment
variable or an Ansible extra variable.

## Concept: protect values before using secrets

**Secrets** in a variable group has **Extra variables** (API type `var`) and
**Environment variables** (type `env`). The campaign proved both reached the
play by comparing digests. API reads returned names and types without values.

**Semaphore does not mask a secret the play prints.** A disposable canary
appeared verbatim in both task output and raw output. Ansible's `no_log: true`
hid the corresponding task output. Put `no_log: true` on every task that
handles a sensitive value, including validation and error-producing tasks.
Never debug all variables or test masking with a real credential.

For example, a protected check for a privately supplied `demo_credential`
would be this task; do not add a credential to the harmless exercise:

```yaml
- name: Check that a private input exists without logging it
  ansible.builtin.assert:
    that:
      - demo_credential is defined
      - demo_credential | length > 0
  no_log: true
```

Group `var` secrets are passed as separate `--extra-vars name=value`
arguments after the JSON values. In the recorded test, a space split one such
value at its first word; survey secrets passed through JSON retained spaces.
Do not assume these two input paths have identical encoding.

`no_log` controls Ansible output, not process inspection. In the tested native
installation, extra-variable values were visible in the running process's
arguments to another local user. Environment secrets were in the process
environment, readable by root and the service account. Keep execution hosts
trusted; see [identity and credentials](15-identity.md) for credential choices.

## Do: collect a survey

**Where: browser, as a project administrator.**

Edit **Inputs demo → Survey Variables → Add variable**. Add these fields;
give each a readable **Title**, then save the template:

| Name | Type | Pass variable as | Required | Default value / choices |
| --- | --- | --- | --- | --- |
| `demo_colour` | Enum | Extra variable | Yes | Blue=`blue`, Green=`green`; default `green` |
| `demo_count` | Integer | Extra variable | Yes | `2` |
| `DEMO_MODE` | String | Environment variable | Yes | `survey` |

Run it with green, `3`, and `survey`. Expect those values in the report; the
survey environment target (`target: "env"`) replaces `DEMO_MODE` in the process
environment and removes it from the extra-variable set. Secret survey fields
can also use that target. Other target names were rejected with HTTP 400.

**Survey values passed as Extra variable are evaluated as Jinja templates by
Ansible.** A value such as `{{ lookup(...) }}` can execute when used. The
campaign's harmless arithmetic-and-lookup probe executed as the service user.
Do not accept untrusted template text. The assertions above enforce business
values after evaluation; they cannot prevent the lookup from running first.

## Check: distinguish form rules from enforcement

The pinned UI offers these types. The campaign checked their delivered values
using API requests shaped like the form:

| Type | What to expect |
| --- | --- |
| String | A string delivered as an extra variable by default. |
| Integer | The form-shaped value `"42"` arrived as a string; validate its spelling and range before converting. |
| Enum | The chosen value is delivered, rather than its display name. |
| Text | Newlines survive in a multiline value. |
| Secret | Supplied through the task's transient `secret` field; absent from the stored task record, but not automatically masked if printed. |

**Required, type, enum membership and defaults are UI rules only.** Direct API
launches omitted required/defaulted values and supplied `abc` for an integer
and `purple` for an enum; the probe still ran with those values. The API does
not turn a survey into an input policy. Retain `ansible.builtin.assert` checks
in the playbook, even when the browser form looks restrictive.

Try count `4`: it is an integer the form can accept, but this playbook must
fail its assertion before the report task. Restore `2` and confirm it passes.
Do not use a secret for either check.

## Concept: launch controls have separate gates

The following behavior was observed with both permissive and locked templates.
The labels are check boxes under **Prompts** or **Ansible prompts**:

| Control | Template permission / task field | Recorded behavior |
| --- | --- | --- |
| Limit | `task_params.allow_override_limit` / `params.limit` | Allowed: changed the actual host limit. Off: task value stored but silently ignored; template limit used. |
| Branch | `allow_override_branch_in_task` / `git_branch` | Allowed with a cloned Git repository: changed marker and commit. Off: template branch ran despite the requested branch. |
| CLI args | `allow_override_args_in_task` / `arguments` | Allowed: appended arguments took effect. Off: stored arguments were silently ignored. |
| Extra variables | Task `environment`, a JSON-encoded object | No corresponding gate: merged over group JSON even on the locked template. |

Task CLI `-e` arguments came last and won duplicate extra-variable keys. Leave
arbitrary CLI overrides off for this exercise. A “locked” template does not
freeze all its data. Inspect what ran, not only what the task record stores.

A **local-folder repository has no branches**: Semaphore runs its working
tree. Branch override needs a real Git repository that Semaphore clones. The
campaign checked branch markers and commits, then checked a run without an
override returned to the default. A branch-shaped value on a local-folder
task record is not evidence of a checkout.

The tested nonexistent host limit failed with no hosts to target. Tags,
skip-tags, verbosity and Galaxy-install prompts exist in the pinned source,
but their combinations are not tested by this inputs exercise.

## Check: interpret rejected launches

API users should validate JSON before sending it and inspect task history
after an error. [Chapter 17](17-api-and-integrations.md) covers API access.

| Invalid input tested | HTTP / effect in 2.19.12 |
| --- | --- |
| Group extra variables: malformed JSON, array, or empty key | 400; rejected. |
| Group environment value: nested object | 400; environment values must be scalar. |
| Group secret type | 400, but the group had already been created; inspect before retrying. |
| Template arguments: malformed JSON; survey target: unknown value | 400; rejected. |
| Entire task body: malformed JSON | 400; rejected. |
| Task `environment`: malformed embedded JSON | **500 with empty body; an error task row remained.** |
| Task `params`: wrong type | **500 with empty body; no task row created.** |
| Task branch: invalid name syntax | **500 with empty body; no task row created.** |
| Task `arguments` or `secret`: malformed embedded JSON | Accepted, then task status `error` with a parse failure. |

These are distinct failure paths. A 500 does not by itself tell you whether a
task row exists. The branch result concerns invalid name syntax, not every
possible missing or inaccessible Git branch.

## Concept: views and build versions

The 2.19.12 source shows template **Views** as organization and filtering by
`view_id`, not an authorization boundary. Template-view creation was **not
tested** in this campaign; use [project roles](15-identity.md) for access.

**Build** and **Deploy** template types were tested with harmless Bash scripts.
A Build starting at `1.0.0` produced that version, then `1.0.1`; a task request
for `9.9.9` did not replace the incremented version. A Deploy template linked
through **Build Template**, with **Autorun** enabled, ran after each successful
Build. Its `build_task_id` pointed to that Build, and its output reported the
incoming version through `SEMAPHORE_TASK_INCOMING_VERSION`.

The form's **Build Version** choices listed successful builds, newest first.
A manual Deploy selected the older build successfully. An API Deploy without
`build_task_id` also ran, so the relationship is not mandatory API validation.
Another Deploy could reference a Deploy task and receive the original incoming
version. These observations show version metadata and task sequencing; they
do not establish artifact storage or a production promotion policy.

**Workflows and workflow approvals are paid Pro features.** Build/Deploy does
not provide those features. Similarly, OpenTofu confirmation is a pause at
`waiting_confirmation` between plan and apply, not a separate-approver system.
See [other task apps](appendices/other-apps.md) for script inputs, exit status
and a local-only OpenTofu exercise. Native Terraform state storage and task
summary/stage features are paid boundaries, not part of that CLI exercise.

## Do: clean up

**Where: browser, as a project administrator.**

After all demo runs finish, remove **Inputs demo**, then **Inputs demo first**
and **Inputs demo second**. Retain the inventory, repository and credentials
from chapter 6. Review any error-created group before deleting it by name.

**Where: controller, as the lab folder's owner.** If you copied the playbook
into the lab folder, remove `/opt/ansible-lab/examples/input-demo.yml`.
