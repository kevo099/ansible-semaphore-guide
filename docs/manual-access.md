# SSH, sudo and the automation account by hand

[Back to the guide](../README.md) · [Previous: the controller by hand](manual-controller-ubuntu.md) · [Next: command-line lessons](05-cli-lessons.md)

Most readers prepare their targets with the scripts of
[Stage 2](stage-2-existing-machines.md) or [Stage 3](stage-3-new-vms-cloud-init.md)
and add them in [Stage 4](stage-4-add-target-first-job.md). This page reaches
the same result by hand, step by step, and continues
[the manual controller path](manual-controller-ubuntu.md).

## Goal

Give the controller verified access to each target, using a dedicated automation
key and an explicitly configured privilege-escalation path.

## Step 1: generate the automation key

**Where: controller, as your normal administrator.**

```bash
install -d -m 0700 ~/.ssh
ssh-keygen -t rsa -b 4096 -f ~/.ssh/ansible_lab -C ansible-automation
```

Use a fresh filename. If it already exists, inspect the existing key's ownership
and purpose rather than replacing it. The command asks for a passphrase. An
interactive CLI user can unlock a protected key through `ssh-agent`; Semaphore
must also have whatever passphrase its stored key requires. For an unattended
disposable lab, an unencrypted dedicated key is another explicit choice: keep
its file private and limit where its public key is authorized.

```bash
chmod 600 ~/.ssh/ansible_lab
ssh-keygen -lf ~/.ssh/ansible_lab.pub
```

**Check:** you have a private key and its `.pub` companion. Only the public file
will be copied to the targets. RSA 4096 avoids assuming that an Ed25519 key will
remain usable under every later system crypto policy.

## Step 2: authenticate each target's host key

**Where: the target's trusted VM console.**

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub
```

Record the fingerprint privately. On the controller, make your first connection
to the **same address or hostname that your inventory will use**:

```bash
ssh -o HostKeyAlgorithms=rsa-sha2-512,rsa-sha2-256 \
  YOUR_ADMIN@ubuntu.example.test
```

Compare the fingerprint in the SSH prompt to the trusted-console value before
accepting it. Repeat for `alma.example.test`. `ssh-keyscan` can collect a key,
but does not authenticate its owner; scanning alone is not the trust check.
If the target accepts only your workstation's key, the login then fails with
`Permission denied (publickey)`. SSH saved the accepted host key before it
tried to log in, which is all this step needs; step 3 deals with the login.

**Check, back on the controller:**

```bash
ssh-keygen -F ubuntu.example.test -f ~/.ssh/known_hosts
ssh-keygen -F alma.example.test -f ~/.ssh/known_hosts
```

Your own names or IPs replace the examples. A reused IP with a changed host key
requires independent verification. Do not turn off host checking to bypass it.

## Step 3: prepare a dedicated target account

Steps 3 and 4 are also available as one playbook,
[`onboard/existing/bootstrap-existing-vm.yml`](../onboard/existing/bootstrap-existing-vm.yml),
run from the controller as the target's own administrator, as
[Stage 2](stage-2-existing-machines.md#do-let-the-controller-do-it-with-the-bootstrap-playbook)
shows. On a controller made by the installer, pass it the exported service key,
or it replaces the key Semaphore uses. The same steps also run as root on the
target with [`onboard/existing/onboard-linux.sh`](../onboard/existing/onboard-linux.sh),
over SSH, from the console or through Azure Run Command, and a new VM can do
them at first boot with
[`onboard/new-vm/cloud-init.yaml`](../onboard/new-vm/cloud-init.yaml), as
[Stage 3](stage-3-new-vms-cloud-init.md) shows. On a controller made by the
installer, each of them ends with what `add-target.sh` needs to add the VM, as
[Stage 4](stage-4-add-target-first-job.md#do-add-the-target-with-add-targetsh)
shows. The manual steps below explain what they do.

First copy the public key from the controller to each target administrator's
home directory. This `scp`, like step 2's first connection, logs in to the
target as your administrator. A cloud-image build usually accepts only the
public key you supplied from your workstation, so the copy fails with
`Permission denied (publickey)`. For this copy only, check that `ssh-add -l`
on your workstation lists that key, then reconnect to your own controller with
`ssh -A YOUR_ADMIN@controller.example.test` so the workstation's agent answers.
Close that session afterwards: while it is open, root on the controller can
use the agent. Alternatively, paste the public key's single line into
`~/ansible_lab.pub` through each target's console. On the controller:

```bash
scp ~/.ssh/ansible_lab.pub YOUR_ADMIN@ubuntu.example.test:ansible_lab.pub
scp ~/.ssh/ansible_lab.pub YOUR_ADMIN@alma.example.test:ansible_lab.pub
```

**Where: each target, using its administrator account.**

Verify that `svc_ansible` is not an existing account used for another purpose.
On a fresh target:

```bash
sudo useradd --create-home --shell /bin/bash svc_ansible
sudo passwd svc_ansible
sudo install -d -o svc_ansible -g svc_ansible -m 0700 /home/svc_ansible/.ssh
sudo install -o svc_ansible -g svc_ansible -m 0600 ~/ansible_lab.pub \
  /home/svc_ansible/.ssh/authorized_keys
```

Choose the account's password and store it in your password manager. One
password shared by the lab targets keeps Semaphore's setup to one credential;
a unique password per target is stronger and needs a credential per target:
one inventory per target, as
[chapter 6](06-semaphore.md#step-2-add-credentials-in-key-store) builds by
hand, or Vault host variables on an installer's controller, as
[Stage 4](stage-4-add-target-first-job.md#do-give-semaphore-the-sudo-password)
shows. It is
used for sudo and console recovery; the SSH configuration below requires
a key for this account. Enter the password interactively, not in a shell
command, inventory or playbook.

For Ubuntu, verify the target prerequisites:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-apt sudo openssh-server
/usr/bin/python3 -c 'import apt'
```

For AlmaLinux, Rocky Linux or registered RHEL 9:

```bash
sudo dnf install -y python3 python3-dnf python3-libselinux sudo openssh-server
/usr/bin/python3 -c 'import dnf'
sudo restorecon -RF /home/svc_ansible/.ssh
```

RHEL package installation needs working subscription repositories. Registration
is performed with your own account outside the playbooks. AlmaLinux and Rocky
Linux use their own repositories and do not need a Red Hat subscription.

## Step 4: configure sudo and the account's SSH policy

**Where: each disposable target.** Edit a new dedicated sudoers file:

```bash
sudo visudo -f /etc/sudoers.d/90-ansible-lab
```

Use these lines:

```sudoers
Defaults:svc_ansible !requiretty
svc_ansible ALL=(ALL:ALL) ALL
```

Then validate:

```bash
sudo chmod 0440 /etc/sudoers.d/90-ansible-lab
sudo visudo -cf /etc/sudoers
sudo -l -U svc_ansible
```

There is no `NOPASSWD` rule in this example. Ansible can use pipelining without
a required TTY, while sudo still asks for the account's password. Privileged
automation on production systems needs its own reviewed authorization model.

Keep your administrator session and console available. Add an account-specific
SSH drop-in rather than changing access for unrelated users:

```bash
sudo tee /etc/ssh/sshd_config.d/70-ansible-lab.conf >/dev/null <<'EOF'
Match User svc_ansible
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
Match all
EOF
sudo chmod 0600 /etc/ssh/sshd_config.d/70-ansible-lab.conf
sudo /usr/sbin/sshd -t
```

Check the effective settings for `svc_ansible` with `sshd -T -C` using your own
controller address:

```bash
sudo /usr/sbin/sshd -T -C user=svc_ansible,host=controller.example.test,addr=CONTROLLER_IP
```

Look for `authenticationmethods publickey`, `passwordauthentication no` and
`kbdinteractiveauthentication no`. Resolve configuration conflicts before
reloading. On Ubuntu use `sudo systemctl reload ssh`; on Enterprise Linux use
`sudo systemctl reload sshd`. This reload is a deliberate access-policy change.

## Step 5: test all three layers

**Where: controller.** First check direct SSH:

```bash
ssh -i ~/.ssh/ansible_lab -o IdentitiesOnly=yes \
  svc_ansible@ubuntu.example.test
```

Inside that session:

```bash
id
sudo -k
sudo -n true
sudo -v
sudo id -u
```

The noninteractive `sudo -n true` should fail because a password is required.
`sudo -v` should accept the account's password; `sudo id -u` should then print
`0`. Repeat on the Enterprise Linux target with its password.

Next, create the controller's private inventory from the repository root:

```bash
cp inventories/lab.ini.example inventories/lab.ini
$EDITOR inventories/lab.ini
/opt/ansible-venv/bin/ansible-inventory --graph
/opt/ansible-venv/bin/ansible-playbook playbooks/baseline/ping.yml \
  --limit lab-ubuntu --private-key ~/.ssh/ansible_lab
/opt/ansible-venv/bin/ansible lab-ubuntu -b -K \
  --private-key ~/.ssh/ansible_lab -m ansible.builtin.command -a 'id -u'
```

**Check:** the inventory contains the intended targets, ping returns `pong`,
and the explicit become test returns `0`. Ansible ping checks SSH and Python;
it is not an ICMP ping and does not by itself prove sudo.

Run become-based lessons against **one target at a time** when their sudo
passwords differ. `-K` asks for one password per CLI invocation. For a mixed
fleet, use properly protected per-host secrets rather than putting passwords
in the public inventory; see [Git and Vault](07-git-and-vscode.md).

## Step 6: install target trust for Semaphore

The service uses a separate known-hosts file. Skip this step on a controller
made by either installer: `add-target.sh` already maintains that file, and the
block below replaces it. After
[the manual controller path](manual-controller-ubuntu.md), on the controller,
copy only the already verified entries for the addresses your inventory uses:

```bash
(
set -e
umask 077
ansible_trust_dir=$(mktemp -d)
ssh-keygen -F ubuntu.example.test -f ~/.ssh/known_hosts > "$ansible_trust_dir/known_hosts"
ssh-keygen -F alma.example.test -f ~/.ssh/known_hosts >> "$ansible_trust_dir/known_hosts"
sudo install -o root -g semaphore -m 0640 "$ansible_trust_dir/known_hosts" \
  /etc/semaphore/known_hosts
rm -- "$ansible_trust_dir/known_hosts"
rmdir -- "$ansible_trust_dir"
)
```

Verify both lookups produced entries before installing the file. These are
public host keys, but they are operational trust data and do not belong in the
public repository.

## Concept

The client key proves who Ansible is. The pinned host key proves which target
it reached. Sudo separately authorizes privileged work after login. All three
must be correct, in both the terminal and the Semaphore service context.
