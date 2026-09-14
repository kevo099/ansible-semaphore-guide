# 7. Edit with Git and VS Code

[Previous: Semaphore](06-semaphore.md) · [Next: operations](08-operations.md)

## Goal

Make small, reviewable changes and understand exactly when new code reaches a
job. Keep your lab's inventory and credentials separate from public examples.

## Do: create your own working copy

Fork this repository or copy it into a repository you own. Use a private
repository for exercises that describe actual hosts, organizational settings
or encrypted lab data. Configure Git's author identity with your own values.

```bash
git switch -c exercise/change-web-message
git status --short
```

Edit `lab_web_message` or the HTML template. Then inspect and validate the
specific change before committing:

```bash
git diff -- playbooks/webserver.yml playbooks/templates/practice.html.j2
git diff --check
/opt/ansible-venv/bin/ansible-playbook playbooks/webserver.yml --syntax-check
git add playbooks/webserver.yml playbooks/templates/practice.html.j2
git diff --cached
git commit -m "Change the practice web page message"
git push -u origin exercise/change-web-message
```

Stage named files. `.gitignore` is helpful, but it is not a secret detector and
does not remove files already tracked by Git. Inspect the staged diff and run
the repository validator before publication. If a real credential is exposed,
revoke/rotate it; deleting the latest file alone does not remove it from history.

**Check:** the remote branch contains only the intended source change. Point
your own Semaphore template at that reviewed branch, launch a task and verify
the new message actually reaches the target. Restore the template's normal
reviewed ref after the experiment.

## What merging changes

Merging changes the repository branch. It does not inherently install a package,
restart a service or run a playbook. However:

- A Semaphore template using a moving branch can fetch its new contents on the
  next task run. A schedule or webhook may cause that task to run automatically.
- A GitHub Actions workflow or another deployment system may react to a merge.
- A template pinned to a tag stays on that tag until its configuration changes,
  assuming the tag itself has not been moved.

Check the actual repository workflows, hooks, schedules and template refs
before treating a merge as operationally inert. For production, use reviewed
version promotion and appropriately controlled credentials.

## Do: edit through VS Code Remote SSH

**Where: workstation.** Connect VS Code Remote SSH to your controller using your
administrator account. Open your ordinary user's working copy, not
`/etc/semaphore` or the service's runtime task clone.

Useful editor features include YAML validation, the Ansible extension, Git
diffs and an integrated terminal. Select the controller's Ansible virtual
environment when configuring editor tools. Use a normal terminal to confirm
which `ansible-playbook` binary the editor invokes.

If VS Code runs remotely on the controller, privately forward its port 3000
to a local workstation port and open the local browser URL. If your remote
session is on an intermediate jump host instead, first establish an SSH tunnel
from that host to the controller; forwarding a jump host's unused port does
not magically reach Semaphore. Keep any forwarded port private.

See [VS Code Remote SSH](https://code.visualstudio.com/docs/remote/ssh) for the
client's supported connection and forwarding behavior.

## Do: add variables without adding secrets

Non-sensitive variables can live in playbooks or ordinary group variables in
your private working repository. Use `ansible-doc` to understand a module's
inputs rather than guessing their names:

```bash
/opt/ansible-venv/bin/ansible-doc ansible.builtin.template
/opt/ansible-venv/bin/ansible-doc ansible.builtin.user
```

For multiple target sudo passwords in a single CLI run, an optional approach
is to keep encrypted host variables under your private working inventory:

```bash
mkdir -p inventories/host_vars
/opt/ansible-venv/bin/ansible-vault create inventories/host_vars/lab-ubuntu.yml
```

Enter `ansible_become_password` and the target's actual password **inside the
Vault editor**, never as a command-line value. Create the matching encrypted
file for `lab-alma`. Unlock them with `--ask-vault-pass` when running Ansible,
or configure a protected Vault credential in your own Semaphore project.

This public repository ignores local inventory files and directories. Keep
Vault content and its unlocking credential separate. An encrypted file is
still operational secret material and is not needed in the public guide.

The guide's first Semaphore path instead uses separate single-target
inventories with separate Key Store sudo credentials. Learn that simpler path
before combining per-host secrets and Vault.

## Optional: a reviewed local repository on the controller

Some operators prefer Semaphore to read a root-owned bare repository through
`file:///opt/ansible-guide.git`. This decouples the runner from remote branch
updates, but introduces a deliberate code-promotion step.

Create that bare repository from a reviewed commit using your administrator's
deployment process. Grant the service read access, keep write access with the
owner, and add only that exact path to `/etc/semaphore/gitconfig`:

```gitconfig
[safe]
    directory = /opt/ansible-guide.git
```

Do not use `safe.directory=*`. Test the service's read access and the selected
ref after promotion. The service's writable task clones belong under
`/var/lib/semaphore`; they are not the canonical source to edit or back up as
your only Git copy.

## Check

You should be able to identify: the commit in your working copy, the remote
branch/ref selected by Semaphore, the credentials and inventory used by the
job, and the change observed on the target. A Git push proves only the first
delivery step; verify an actual job before claiming deployment.

## Concept

Version control records intent. A task applies a particular version of that
intent to particular hosts. Clear promotion and verification make those two
events traceable.
