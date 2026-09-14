# 6. Run the lessons through Semaphore

[Previous: CLI lessons](05-cli-lessons.md) · [Next: Git and VS Code](07-git-and-vscode.md)

## Goal

Run the same reviewed playbooks through Semaphore and understand the connection
between a project, repository, inventory, credential and task template.

Complete the CLI SSH/Python/sudo checks first. A UI cannot repair an incorrect
target bootstrap. Labels below follow the Community workflow; some releases
call variable groups “environments.” Do not assume a feature in newer online
documentation exists in the pinned release.

## Open your private browser connection

**Where: workstation.** Keep this SSH session open:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8088:127.0.0.1:3000 \
  YOUR_ADMIN@controller.example.test
```

Open `http://127.0.0.1:8088/`, log in with your own Semaphore account, and make
sure you can log out and back in. Your SSH administrator and Semaphore UI
administrator are separate identities.

## Step 1: create a project

Create a project named **Ansible Practice**. Use one project while learning so
you can easily see how its objects relate. Do not add automatic schedules yet.

**Concept:** a project groups automation resources and access to them. It does
not create a new Ansible runtime or an isolated virtual machine by itself.

## Step 2: add credentials in Key Store

Create the following entries using credentials generated in your own lab:

| Entry name | Type | Contents |
| --- | --- | --- |
| `Practice target SSH` | SSH | Login `svc_ansible`; the dedicated automation private key; its passphrase if required. |
| `Ubuntu sudo` | Login with password | Login `svc_ansible`; the Ubuntu target's sudo password. |
| `Alma sudo` | Login with password | Login `svc_ansible`; the Alma target's sudo password. |
| `No repository credential` | None | Used for the public HTTPS example repository. |

Enter these through the private browser session. Do not paste a secret into an
inventory, variable group, task argument, commit message or screenshot. A
public key is not a replacement for the private key required by the runner.

The Key Store encrypts stored access keys with the controller's
`access_key_encryption` setting. Anyone who can recover both the database and
that key can potentially recover the stored credentials; protect the recovery
set accordingly. See [Semaphore's Key Store documentation](https://semaphoreui.com/docs/user-guide/key-store).

## Step 3: create two inventories

Create one inventory per target for the first lessons. This lets you use a
different sudo password on each host without placing it in inventory text.

For **Ubuntu practice**, choose a static INI inventory and enter:

```ini
[lab]
lab-ubuntu ansible_host=ubuntu.example.test ansible_user=svc_ansible ansible_python_interpreter=/usr/bin/python3
```

Replace the example address. Select **Practice target SSH** for its SSH/user
credential and **Ubuntu sudo** for its sudo credential.

For **Alma practice**, use:

```ini
[lab]
lab-alma ansible_host=alma.example.test ansible_user=svc_ansible ansible_python_interpreter=/usr/bin/python3
```

Select the same dedicated SSH credential and **Alma sudo**. The corresponding
host keys must already be in `/etc/semaphore/known_hosts` for the exact names
or addresses used here. The `lab` group is required by the included playbooks.

**Check:** neither inventory contains the controller. Each contains exactly
one intended target. See [inventory types and credentials](https://semaphoreui.com/docs/user-guide/inventory).

## Step 4: add the repository

Add a repository named **Guide examples**:

| Field | Value |
| --- | --- |
| URL | `https://github.com/kevo099/ansible-semaphore-guide.git` |
| Branch/ref | `v1.0.0` for the initial reviewed examples |
| Credential | `No repository credential` |

The release tag gives the job a deliberate version of the examples. For your
own exercises, fork/copy the project, create a private working repository and
select your reviewed branch or tag. A private Git repository needs its own
appropriately scoped read credential; it does not need your target SSH key.

The controller service must be able to reach the repository and trust its TLS
certificate. Do not disable certificate verification to make a clone work.

**Concept:** Git stores the playbooks. The inventory supplies the hosts. Keeping
them separate allows the same playbook to run against different approved labs.

## Step 5: create variable groups

Create **Practice defaults** with empty Ansible variables:

```json
{}
```

Create **Allow required reboot** with:

```json
{"allow_reboot": true}
```

The second group is only for the separately selected patch/reboot template.
Use a JSON boolean, not the string `"true"`. Do not add passwords here.

## Step 6: create task templates

Select **Ansible Playbook** as the template type. Set the repository to **Guide
examples**, the appropriate inventory, and **Practice defaults**, except for
the explicitly named reboot template. Playbook paths are relative to the
repository root.

| Template | Playbook | Extra CLI arguments, as a JSON array |
| --- | --- | --- |
| Ubuntu — Ping | `playbooks/ping.yml` | `["--limit", "lab-ubuntu"]` |
| Ubuntu — Baseline preview | `playbooks/baseline.yml` | `["--limit", "lab-ubuntu", "--check", "--diff"]` |
| Ubuntu — Baseline apply | `playbooks/baseline.yml` | `["--limit", "lab-ubuntu", "--diff"]` |
| Ubuntu — Users | `playbooks/users.yml` | `["--limit", "lab-ubuntu"]` |
| Ubuntu — Webserver | `playbooks/webserver.yml` | `["--limit", "lab-ubuntu"]` |
| Ubuntu — Patch preview | `playbooks/patch.yml` | `["--limit", "lab-ubuntu", "--check", "--diff"]` |
| Ubuntu — Patch, no reboot | `playbooks/patch.yml` | `["--limit", "lab-ubuntu"]` |
| Ubuntu — Patch, allow required reboot | `playbooks/patch.yml` | `["--limit", "lab-ubuntu"]` plus the reboot variable group |

Make equivalent Alma templates using **Alma practice** and `lab-alma`. Keep
interactive argument overrides and schedules disabled while you learn the
fixed templates. Do not add `-K` to a noninteractive UI job: the selected sudo
credential supplies that authentication. Do not put a password in CLI arguments.

If your UI provides a dedicated limit field, use it consistently and avoid
duplicating conflicting limits in extra arguments. Confirm the effective
command and target recap in the task log. The included preflight rejects a
missing limit and literal `all` or `*` values before SSH.

The current [Semaphore Ansible documentation](https://semaphoreui.com/docs/user-guide/apps/ansible)
describes repository-relative paths, task arguments and credential selection.

## Step 7: qualify a complete job

1. Run **Ubuntu — Ping**. Verify target identity, `changed=0`, and no failures.
2. Run **Baseline preview**. Read all predicted changes and skipped tasks.
3. Run **Baseline apply**. Verify the target banner and time service separately.
4. Repeat **Baseline apply**. Expect no immediate managed-state changes.
5. Change the banner manually on the disposable target, rerun the template,
   and verify the specific drift was repaired.
6. Repeat the same sequence with the Alma target and its own sudo credential.

A task's final status can appear before the last output has finished arriving.
Wait for the full host recap before interpreting a log. If a job is queued,
remember that this controller starts with `max_parallel_tasks: 1`.

## Why the terminal can work while Semaphore fails

The terminal and service use different users, home directories, SSH agents,
known-hosts files and environment variables. In particular, Semaphore's
per-task SSH agent must be allowed to offer its stored key. Do not add
`IdentitiesOnly=yes` to shared task SSH options without a corresponding
`IdentityFile`; doing so can hide the agent key. Explicit `-i` terminal
connections have a different identity-selection path.

Keep strict host verification. Correct the service's actual known-hosts file,
permissions, inventory or credentials rather than bypassing authentication.

## Concept

A successful template is a repeatable combination of a code revision, target
inventory, credentials, variables and execution options. Record all of them
when comparing a successful run to a later failure.
