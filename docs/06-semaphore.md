# 6. Run the lessons through Semaphore

[Previous: CLI lessons](05-cli-lessons.md) · [Next: Git and VS Code](07-git-and-vscode.md)

## Goal

Run the same reviewed playbooks through Semaphore and understand the connection
between a project, repository, inventory, credential and task template.

Complete the CLI SSH/Python/sudo checks first. A UI cannot repair an incorrect
target bootstrap. Labels below are the ones Semaphore Community 2.19.12 shows;
older releases call variable groups “environments.” Do not assume a feature in
newer online documentation exists in the pinned release.

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

Use **Key Store → New Key** to create the following entries with credentials
generated in your own lab:

| Entry name | Type | Contents |
| --- | --- | --- |
| `Practice target SSH` | SSH Key | Username `svc_ansible`; the dedicated automation private key; its passphrase if required. |
| `Ubuntu sudo` | Login with password | Username **left empty**; Password: the Ubuntu target's sudo password for `svc_ansible`. |
| `Alma sudo` | Login with password | Username **left empty**; Password: the Alma target's sudo password for `svc_ansible`. |
| `No repository credential` | None | Used for the public HTTPS example repository. A new project already contains an entry named **None** of this type; you can use it instead. |

Leave the Username of the two sudo entries empty. Semaphore passes a sudo
credential's username to Ansible as `--become-user`, the account to *become*,
not the account that logs in. `svc_ansible` there would make every privileged
task run as `svc_ansible` instead of root. Runs that change nothing still look
green, and the first real change fails with an error such as
`Destination /etc not writable`. The login account comes from the inventory's
**User Credentials** entry.

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

Use **Inventory → New Inventory → Ansible Inventory**. For **Ubuntu practice**,
set **Type** to **Static** and enter:

```ini
[lab]
lab-ubuntu ansible_host=ubuntu.example.test ansible_user=svc_ansible ansible_python_interpreter=/usr/bin/python3
```

Replace the example address. Select **Practice target SSH** as **User
Credentials** and **Ubuntu sudo** as **Sudo Credentials**. The sudo list only
offers “Login with password” entries.

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

Use **Repositories → New Repository** to add **Guide examples**:

| Field | Value |
| --- | --- |
| URL or path | `https://github.com/kevo099/ansible-semaphore-guide.git` |
| Branch / Tag | `v1.0.0` for the initial reviewed examples |
| Access Key | `No repository credential` (or the built-in **None**) |

The release tag gives the job a deliberate version of the examples. A tag
cannot be fast-forwarded, so Semaphore clones a tag-pinned repository again for
each run; that is expected and needs access to the Git host when the task
starts. For your own exercises, fork/copy the project, create a private working
repository and select your reviewed branch or tag. A private Git repository
needs its own appropriately scoped read credential; it does not need your
target SSH key.

The controller service must be able to reach the repository and trust its TLS
certificate. Do not disable certificate verification to make a clone work.

**Concept:** Git stores the playbooks. The inventory supplies the hosts. Keeping
them separate allows the same playbook to run against different approved labs.

## Step 5: create variable groups

Use **Variable Groups → New Group**. Create **Practice defaults** with empty
extra variables:

```json
{}
```

Create **Allow required reboot**, switch **Extra variables** from **Table** to
**JSON**, replace the editor's default `{}` and enter:

```json
{"allow_reboot": true}
```

The second group is only for the separately selected patch/reboot template.
Use a JSON boolean, not the string `"true"`. Do not add passwords here; the
group's **Secrets** tab is not needed for these lessons.

## Step 6: create task templates

Use **Task Templates → New template → Ansible Playbook**. Fill in **Name**,
**Repository** (**Guide examples**), **Path to playbook file** (relative to the
repository root), **Inventory** and **Variable Groups** (**Practice defaults**,
except for the explicitly named reboot template). Under **Ansible options**,
use **Limit → Add limit** for the target. Under **CLI args**, add each extra
argument as its own entry.

| Template | Path to playbook file | Limit | CLI args |
| --- | --- | --- | --- |
| Ubuntu — Ping | `playbooks/ping.yml` | `lab-ubuntu` | none |
| Ubuntu — Baseline preview | `playbooks/baseline.yml` | `lab-ubuntu` | `--check`, `--diff` |
| Ubuntu — Baseline apply | `playbooks/baseline.yml` | `lab-ubuntu` | `--diff` |
| Ubuntu — Users | `playbooks/users.yml` | `lab-ubuntu` | none |
| Ubuntu — Webserver | `playbooks/webserver.yml` | `lab-ubuntu` | none |
| Ubuntu — Patch preview | `playbooks/patch.yml` | `lab-ubuntu` | `--check`, `--diff` |
| Ubuntu — Patch, no reboot | `playbooks/patch.yml` | `lab-ubuntu` | none |
| Ubuntu — Patch, allow required reboot | `playbooks/patch.yml` | `lab-ubuntu` | none; select the **Allow required reboot** variable group |

Make equivalent Alma templates using **Alma practice** and `lab-alma`. Leave the
**Prompts** and **Ansible prompts** check boxes and schedules off while you learn
the fixed templates. Do not add `-K` to a noninteractive UI job: the selected
sudo credential supplies that authentication. Do not put a password in CLI
arguments.

This release passes the Limit option to Ansible as `--limit`. Putting
`--limit lab-ubuntu` in CLI args instead also works, but do not set both: two
limits in one template make the effective target hard to read. Confirm the
target recap in the task log. The included preflight rejects a missing limit
and literal `all` or `*` values before SSH.

The current [Semaphore Ansible documentation](https://semaphoreui.com/docs/user-guide/apps/ansible)
describes repository-relative paths, task arguments and credential selection.

## Step 7: qualify a complete job

Launch a template with its run (▶) button, then **Run** in the dialog. The
dialog's **Dry Run** (`--check`) and **Diff** (`--diff`) switches apply to that
one run only; the preview templates keep those arguments fixed so a preview is
repeatable.

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

Privilege escalation is also configured differently. The terminal's `-K`
password is used to become root; a Semaphore sudo credential with a Username
becomes that user instead (see step 2). If Baseline apply works from the
terminal but fails in Semaphore only when something needs changing, check that
the sudo credential's Username is empty.

## Concept

A successful template is a repeatable combination of a code revision, target
inventory, credentials, variables and execution options. Record all of them
when comparing a successful run to a later failure.
