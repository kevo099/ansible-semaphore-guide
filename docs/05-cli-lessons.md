# 5. Run, inspect and change the playbooks

[Previous: access](04-access.md) · [Next: Semaphore](06-semaphore.md)

**Where: controller, as your normal administrator, from the repository root.**
Use your local inventory and the automation key you created. The examples
choose `lab-ubuntu`; repeat each exercise separately with `lab-alma` and its
own sudo password.

## Goal

Understand the playbook's effect before adding a web UI: select the host,
preview supported changes, apply them, check the outcome and repeat.

## Establish the command-line environment

```bash
cd ~/ansible-semaphore-guide
. /opt/ansible-venv/bin/activate
ansible --version
ansible-inventory --graph
ansible-playbook playbooks/ping.yml --limit lab-ubuntu --list-hosts
```

On the [seeded Enterprise Linux controller](03-controller-el9.md), run
`cd /opt/ansible-lab` (or your `--lab-dir`) instead of the first command. Its
`ansible.cfg` reads the inventory Semaphore uses, with the host names you gave
`add-target.sh`. If you chose
[3b's Vault option](03-controller-el9.md#do-give-the-templates-the-targets-sudo-password)
for sudo passwords, Ansible decrypts those files for every play there, Ping
included: add `--ask-vault-pass` to each `ansible` and `ansible-playbook`
command and leave out `-K`, because each host's file supplies its own sudo
password.

Expect exactly the host you intend. The configured target login is
`svc_ansible`; your controller administrator is the person running Ansible.
`--private-key` selects the target key. `-K` asks for the become/sudo password,
not the SSH key's passphrase.

For a passphrase-protected SSH key, you can use an agent in your controller
session:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/ansible_lab
```

An agent stores an unlocked key in memory for that session. Do not forward
your everyday workstation agent to untrusted hosts. The lesson commands below
still show `--private-key` so the intended key is explicit.

## Lesson 1: prove connectivity

**Do:**

```bash
ansible-playbook playbooks/ping.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab
```

**Check:** `pong`, the expected OS identity, `failed=0`, `unreachable=0`, and
`changed=0`. The preflight checks the OS family and its package-module Python
bindings. It does not install missing bootstrap dependencies for you.

**Concept:** a successful connection check establishes the execution path. It
does not mean that sudo, services or a security baseline have been validated.

## Lesson 2: manage a banner and time service

Read [`baseline.yml`](../playbooks/baseline.yml), then:

```bash
ansible-playbook playbooks/baseline.yml --syntax-check
ansible-playbook playbooks/baseline.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K --check --diff
ansible-playbook playbooks/baseline.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K --diff
ansible-playbook playbooks/baseline.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K --diff
```

**Check:** the real run manages `/etc/motd`, installs chrony and enables/starts
the appropriate time service. The immediate repeat should leave managed state
unchanged. Inspect the target separately:

```bash
ssh -i ~/.ssh/ansible_lab svc_ansible@ubuntu.example.test
cat /etc/motd
systemctl is-active chrony
systemctl is-enabled chrony
exit
```

On Enterprise Linux the service name is `chronyd`.

**Concept:** idempotence means that applying the same desired state again does
not keep rewriting it. A later package-cache refresh can report a change
without meaning that a managed configuration drifted.

### Deliberate drift exercise

On the disposable Ubuntu target, use your administrator to change `/etc/motd`
to a different message. Preview the baseline again, predict which task should
change, then apply it and verify that the managed banner returns. Run one more
time and confirm no further configuration change is needed.

## Lesson 3: create ordinary users

```bash
ansible-playbook playbooks/users.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K --check --diff
ansible-playbook playbooks/users.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K
ansible-playbook playbooks/users.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K
```

**Check on the target:**

```bash
getent group lab_learners
id lab_alice
id lab_bob
```

The playbook creates reserved `lab_` users with locked passwords and no extra
groups, sudo grant or SSH key. It does not manage your administrator or
`svc_ansible`. Adding `lab_charlie` to `lab_practice_users` is a useful first
edit. Predict the task results before applying it.

Removing a name from the variable list does **not** delete its existing account.
Deletion needs explicit desired state or a clean target rebuild. The lesson
also removes supplementary group memberships from the accounts it owns.

**Concept:** a loop applies the same resource definition to multiple inputs.
The loop does not automatically manage resources that are no longer in its list.

## Lesson 4: deploy a template and use a handler

This lesson owns the entire nginx configuration on a fresh target. It serves
only `127.0.0.1:8080`, so it does not open a network-facing website.

```bash
ansible-playbook playbooks/webserver.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K --check --diff
ansible-playbook playbooks/webserver.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K --diff
ansible-playbook playbooks/webserver.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K --diff
```

**Check:** the playbook validates the nginx configuration before replacing it,
starts the service, and checks both HTTP status and the expected page content.
View the page from inside the target with `curl http://127.0.0.1:8080/`.

Change just the page text:

```bash
ansible-playbook playbooks/webserver.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K \
  -e '{"lab_web_message":"My second page version."}' --diff
```

The HTML changes without requiring a service restart. A valid change to nginx's
configuration notifies the reload handler. Inspect the playbook and identify
the difference between the two templates.

**Concept:** handlers respond to relevant changes. They avoid restarting a
service on every run when nothing it needs has changed.

## Lesson 5: patch deliberately

Read [the operations guide](08-operations.md) and establish recovery first.
Then preview and apply updates to one target:

```bash
ansible-playbook playbooks/patch.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K --check --diff
ansible-playbook playbooks/patch.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K
```

Reboot is disabled by default. The playbook reports whether the OS requests
one. A separately planned run can enable it with a real JSON boolean:

```bash
ansible-playbook playbooks/patch.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K -e '{"allow_reboot":true}'
```

`-e allow_reboot=true` supplies a string and is intentionally rejected. Package
updates can restart services even when a full VM reboot is disabled.

**Concept:** package installation, reboot decisions and application readiness
are separate parts of a maintenance operation.

## How to read an Ansible recap

| Field | Interpretation |
| --- | --- |
| `ok` | Tasks that completed successfully, including tasks reporting changes. |
| `changed` | Tasks that reported a change; inspect what they changed. |
| `unreachable` | A connection or authentication path failed. |
| `failed` | A task failed its execution or validation condition. |
| `skipped` | A condition excluded a task; decide whether the skipped work matters. |
| `rescued` / `ignored` | Error handling continued; read the original failure. |

A green check-mode run is a prediction, not a deployment. On a fresh target,
packages, groups or directories may not exist yet. These lessons explain the
dependent work that cannot be checked until the first real apply. This behavior
is described in [Ansible's check-mode documentation](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html).

Avoid `--diff` on tasks containing sensitive configuration. `no_log` can protect
task output when used correctly, but it does not make a secret safe to commit.

## Independent completion check

Before moving to Semaphore, run all five lessons on both target OSes and write
down the expected differences. Explain which tasks use `become`, which files
are owned by a lesson, which changes notify a handler, and why some preview
tasks are skipped on a clean target.
