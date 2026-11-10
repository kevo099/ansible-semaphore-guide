# Stage 4: add the target and run the first job

[Back to the guide](../README.md) · [Previous: Stage 2, existing machines](stage-2-existing-machines.md) or [Stage 3, new VMs](stage-3-new-vms-cloud-init.md) · [Next: go further](../README.md#go-further)

## Goal

The controller's lab inventory lists the target, the service trusts its
verified host key, Semaphore has the targets' sudo password, and the seeded
**Ping** and **Baseline preview** templates succeed for it. The target is then
onboarded, and every lesson in the guide can run against it.

## Before you start

- **The controller from Stage 1,** with the **Ansible Practice** project the
  installer seeded. Its inventory, **Lab inventory file**, is the local file
  `/opt/ansible-lab/inventories/lab.ini`, empty at first. Do not recreate the
  project, and do not set up a Git host to run these templates.
- **The guide's folder** on the controller, `~/ansible-semaphore-guide`: the
  copy of the guide you installed from, or the newer one you updated with. It
  is not the lab folder `/opt/ansible-lab`. `add-target.sh` runs from the
  guide's folder.
- **From Stage 2 or Stage 3, for each target:** the `name=`, `address=`,
  `group=` and `fingerprint=` lines, or, after the bootstrap playbook, the
  whole `add-target.sh` command it printed.
- **The plain sudo password** you gave `svc_ansible`, from your password
  manager.
- **A browser session to Semaphore,** as
  [Stage 1](stage-1-controller.md#do-open-semaphore) shows.

## Do: add the target with add-target.sh

**Where: the controller, as your administrator account, in the guide's
folder.** Type the command yourself, or copy it from this page; do not copy it
from the VM's output:

```bash
cd ~/ansible-semaphore-guide
sudo bash controller/add-target.sh --from-info
```

It asks for the lines:

```text
To cancel, press Ctrl-C and then Ctrl-D.
Paste the name=, address=, group= and fingerprint= lines the VM printed, then press Ctrl-D:
```

Paste the four lines, or the VM's whole output: every other line is ignored.
Lines that start with `onboard:`, as cloud-init logs them, are accepted. Then
press Enter, so the cursor is on a new line, and press Ctrl-D. Ctrl-C and then
Ctrl-D cancels without changing anything. Success looks like this:

```text
Using name=lab-alma address=alma.example.test group=enterprise_linux fingerprint=SHA256:...
Added lab-alma (alma.example.test) to /opt/ansible-lab/inventories/lab.ini under [enterprise_linux] and trusted its verified host key.
Next: run the Ping template, which covers every host in the lab group. If lab-alma fails with Permission denied (publickey),
svc_ansible on lab-alma lacks the key 'sudo cat /etc/semaphore/svc_ansible.pub' shows; if sudo asks for a
password, give Semaphore the targets' sudo password, as docs/stage-4-add-target-first-job.md shows.
```

Running it again with the same lines changes nothing and says
`Already present: ...`. Paste one target's lines per run.

**When a value is missing.** The VM leaves out a value it cannot read, such as
a hostname the inventory reserves, or an address when it has several.
`add-target.sh` then says `The paste has no name= line; give that value with
--name.`, or the same for `--address` or `--fingerprint`. Run it again with
only that option, and a value you read yourself at the VM's console:

```bash
sudo bash controller/add-target.sh --from-info --name lab-alma
```

Take no option from the VM's output. To replace a name the VM printed, paste
the lines again without the `name=` line and add `--name NAME`.

**After the bootstrap playbook,** run the whole command it printed instead,
from the guide's folder, replacing `NAME`, `ADDRESS` or `FINGERPRINT` if they
appear in capitals. It is the explicit form:

```bash
sudo bash controller/add-target.sh --name lab-alma --address alma.example.test \
  --group enterprise_linux --fingerprint 'SHA256:REPLACE_WITH_CONSOLE_VALUE'
```

Use the explicit form yourself when you read the values at the console, for
example a fingerprint from `sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub`:
`--group` is `ubuntu` for Ubuntu and `enterprise_linux` for AlmaLinux, Rocky
Linux and RHEL. Use the RSA host key's fingerprint, as every onboarding file
prints it: a vendor STIG switches Enterprise Linux to a FIPS crypto policy under
which the target stops offering its Ed25519 host key, and a controller that
pinned only that key would then refuse to connect.

**Another lab folder.** If you installed with `--lab-dir DIR`, add the same
`--lab-dir DIR` to every `add-target.sh` command; it otherwise uses
`/opt/ansible-lab`. `--known-hosts FILE` names another known-hosts file than
`/etc/semaphore/known_hosts`, which you do not need on an installed controller.

A VM prepared with an older copy of the onboarding files prints
`sudo bash scripts/add-target.sh --from-info`. Type the command as this page
shows it; the lines to paste are the same.

What it does, in order: it reads the whole paste before anything else and
discards whatever still arrives after it; it takes only the four values and
checks each one as it checks its options; it refuses `localhost`, a group name
such as `lab`, `ubuntu` or `enterprise_linux`, a name the inventory lists with
another address or group, an address it lists under another name, and a group
with no section in the inventory. It then scans the address with
`ssh-keyscan`, keeps only the key whose fingerprint matches, adds the line
`NAME ansible_host=ADDRESS` under the group in `lab.ini`, and only then appends
that key to `/etc/semaphore/known_hosts`. A mismatch changes nothing and prints
the scanned fingerprints, unverified, so you can investigate. Runs on one lab
folder take turns; one that waits more than two minutes for another stops and
changes nothing.

## Why the VM prints lines, not a command

Whoever controls a VM controls what it prints, so the guide treats that output
as untrusted. Pasted into a root shell on the controller, a line that only
looks like the expected command could run anything there. The scripts on the
VM therefore print data, and only reviewed code on the controller acts on it:
`add-target.sh --from-info` reads the whole paste before it does anything,
discards whatever still arrives after it, takes the four values, checks each as
it checks its options, and ignores every other line. The command in the VM's
output is only a reminder: type `sudo bash controller/add-target.sh --from-info`
yourself or copy it from this guide, and paste only after its prompt. Never
paste the VM's output, that line included, into a shell, and take no option
from it: when `add-target.sh` says a value is missing, give it with the option
its own message names, with a value you read yourself. The bootstrap playbook
is the one exception: it runs on the controller and builds its command there,
from the controller's inventory and a fingerprint it checks.

## Do: give Semaphore the sudo password

**Where: Semaphore, in your browser, once per password.** The seeded inventory
has no sudo credential. Until you add one, every template that uses sudo, which
is all of them except **Ping**, stops with `Missing sudo password`.

**One shared sudo password, the default.** If every lab target has the same
`svc_ansible` sudo password, as Stage 2 recommends:

1. Open **Key Store → New Key**. Name it **Lab sudo**, choose the type
   **Login with password**, leave **Username empty**, and enter the sudo
   password as **Password**. Save.
2. Open **Inventory → Lab inventory file**, select **Lab sudo** as **Sudo
   Credentials**, and save.

Leave the Username empty. Semaphore passes it to Ansible as `--become-user`,
the account to become, so `svc_ansible` there would make every privileged task
run as `svc_ansible` instead of root: runs that change nothing still look
green, and the first real change fails with an error such as
`Destination /etc not writable`. One inventory holds one sudo credential, which
is why this way needs the shared password. You do this once; targets you add
later with the same password need nothing more here.

**A different sudo password per target.** Store each target's password as an
encrypted host variable in the lab folder, as the lab folder's owner, your
administrator account by default:

```bash
cd /opt/ansible-lab
mkdir -p inventories/host_vars
/opt/ansible-venv/bin/ansible-vault create inventories/host_vars/lab-ubuntu.yml
/opt/ansible-venv/bin/ansible-vault create inventories/host_vars/lab-alma.yml
sudo chgrp semaphore inventories/host_vars/*.yml
chmod 0640 inventories/host_vars/*.yml
```

Each file is named after the target's inventory name. Use the same Vault
password for every file. Inside each editor, enter one line,
`ansible_become_password: "..."`, with that target's sudo password. Then create
a Key Store entry **Lab vault password** of type **Login with password**,
Username empty, holding the Vault password, and add it to every template under
**Ansible options → Vaults**, Ping included, because Ansible reads all host
variables for every play. Encrypted files are still secrets. The lab folder's
`.gitignore` keeps `inventories/`, and these files with it, out of Git; for a
folder installed before that file existed, see
[moving the lab folder to Git](appendices/git-migration.md). Templates that a
later [controller update](controller-update.md) adds get the same vault
password when all your seeded templates share it.

The service reads the lab folder through the `semaphore` group, which your
account is deliberately not a member of, because that group can also read the
controller's secrets. New files and folders inherit the group from the setgid
folders, so create folders with plain `mkdir` rather than `mkdir -m` or
`install -d -m`, which can drop the setgid bit. Tools that write private files,
such as `ansible-vault create`, need the `chgrp` and `chmod` above before
Semaphore can read them. `find /opt/ansible-lab ! -group semaphore` must print
nothing.

## Do: run Ping and Baseline preview

**Where: Semaphore, the Lessons tab of the Ansible Practice project.** Start a
template with its run (▶) button, then **Run** in the dialog. Both templates
run on every host in the `lab` group, the new one included.

1. Run **Ping**. It needs no sudo, so it works before the previous step. Each
   host reports what answered:

   ```text
   "msg": "lab-alma (alma.example.test) runs AlmaLinux 9.6. Ansible ping proves SSH and Python, not ICMP or sudo."
   ```

   The recap shows `failed=0` and `unreachable=0` for every host. The task log
   has no Git clone step, and its paths are under `/opt/ansible-lab`.
2. Run **Baseline preview**. It runs in check mode with diff, so it changes
   nothing. Read every predicted change: a banner in `/etc/motd`, and the time
   service `chrony`. On a first run it also says
   `CHECK MODE: chrony is not installed yet`, because a preview cannot start a
   service whose package is not installed yet. The recap shows `failed=0`.
   Success here proves the sudo password.

The natural next lesson continues on the same tab:

3. Run **Baseline apply**. It makes the changes the preview showed. Check the
   banner and the time service on the target.
4. Run **Baseline apply** again. The recap shows `changed=0` for every host:
   the target is in the managed state.

A run's status can appear before its last output has arrived: wait for the
complete `PLAY RECAP` before you read a log. The project runs one task at a
time, so a second task waits in the queue until the first finishes. The
dialog's **Dry Run** and **Diff** switches apply to that one run only.
[Chapter 6, step 7](06-semaphore.md#step-7-qualify-a-complete-job) has the
full qualification, including a deliberate drift repair.

When one host fails a task, the lessons stop the other hosts too, and an
unreachable host marks the whole run failed. So a broken or powered-off target
in `lab` gets in the way of all the others: start or fix it, or retire it as
the next section shows.

## Do: rebuild or retire a target

**Where: the controller, as your administrator account.**

**A rebuilt or restored target at the same address** presents new host keys.
Prepare it again, as in Stage 2 or Stage 3, and run `add-target.sh` with its
new lines. It finds the host in the inventory and a different key trusted for
its address, changes nothing, and prints the commands that remove the old key.
After you have confirmed at the console why the key changed, run them:

```bash
sudo ssh-keygen -R alma.example.test -f /etc/semaphore/known_hosts
sudo chown root:semaphore /etc/semaphore/known_hosts && sudo chmod 0640 /etc/semaphore/known_hosts
```

`ssh-keygen -R` rewrites the file as `root:root`; without the `chown` the
service can no longer read it, and every job fails host verification.
`sudo python3.12 controller/check-controller.py`, run in the guide's folder,
reports this as `service_can_read_known_hosts`. Then run `add-target.sh` once more with the same
lines. It checks the new key against the fingerprint as before, adds no second
inventory line, and says:

```text
Trusted the verified host key of lab-alma (alma.example.test), which /opt/ansible-lab/inventories/lab.ini already lists.
```

**To retire a target, or give its address to another VM,** remove its key as
above, then, as the lab folder's owner, copy `lab.ini` aside and remove its
inventory line:

```bash
cp /opt/ansible-lab/inventories/lab.ini ~/lab.ini.before-retire
sed -i '/^lab-alma /d' /opt/ansible-lab/inventories/lab.ini
```

**A rebuilt or reinstalled controller** has a new service key pair. Every
target still authorizes the old public key, so Ping fails with
`Permission denied (publickey)`. Save the new key as `~/svc_ansible.pub`, as
[Stage 1](stage-1-controller.md#do-save-the-service-key) shows, and run the onboarding of
[Stage 2](stage-2-existing-machines.md) again on each target: the script and
the playbook replace the account's authorized keys with exactly the ones you
give them, and leave the password as it is when you give no new one.

## Check

On the controller, the inventory lists the target, and the service trusts a key
for its address:

```bash
grep -n ansible_host /opt/ansible-lab/inventories/lab.ini
sudo ssh-keygen -F alma.example.test -f /etc/semaphore/known_hosts
cd ~/ansible-semaphore-guide
sudo python3.12 controller/check-controller.py
```

The readiness report ends with `"passed": true`. In Semaphore, the **Lab
inventory file** shows **Lab sudo** as its **Sudo Credentials**, or every
template lists **Lab vault password** under **Vaults**. **Ping** and
**Baseline preview** succeed for the new host, and Ping names its
distribution. The target is onboarded.

## Save these values

| Value | Where it came from | Needed for |
| --- | --- | --- |
| The target's inventory name and address | `add-target.sh`'s `Added` line | `--limit` in later lessons; retiring it |
| The **Lab sudo** password, or each target's | Stage 2 or 3; already in your password manager | Recovery, and every new target with the shared password |
| The Vault password, if you chose per-target passwords | You chose it at `ansible-vault create` | Every edit of the host files; the command-line lessons |

## When a step fails

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| `add-target.sh` refuses the pasted lines | A line is missing because the VM could not read its value, or its hostname is one the inventory reserves; a line appears twice; a value is also given as an option; a value is not a plain name, address or fingerprint; or the name is `localhost`, `all`, `ungrouped` or an inventory group's, such as `lab`, `ubuntu` or `enterprise_linux` | Nothing changed. Give the value `add-target.sh` says is missing with the option it names (`--name`, `--address` or `--fingerprint`). For a refused name, paste the lines again without the `name=` line and add `--name NAME`, as its message says. Paste one VM's lines at a time, and read a refused value again at the VM's console, or with [`inventory-info.sh`](stage-2-existing-machines.md#do-read-a-prepared-vms-values-again). |
| `add-target.sh` says `No SSH host key received from ADDRESS` | The controller cannot reach the VM's SSH port at that address | Nothing changed. Check the address, that the VM is running and its SSH service active, and every firewall between them: `firewalld` or `ufw` on the VM, the hypervisor's firewall, such as Proxmox's, a VLAN or routing rule, or a cloud security group, such as the Azure targets' group, which admits SSH only from `azure_target_ssh_source`. From the controller, `ssh-keyscan -t rsa ADDRESS` should print the VM's key. |
| `add-target.sh` says `No scanned key matched` | The fingerprint is from another VM, was mistyped, or the VM was rebuilt | Read the fingerprint again at the VM's console; never take it from the scan. |
| `add-target.sh` says `Known-hosts already contains a different key` | The address belonged to an earlier VM | Verify why, then follow the commands it prints to remove the old key. |
| `add-target.sh` says `Inventory already lists ADDRESS as NAME`, `Inventory already contains NAME with other settings`, or that the inventory lists the name under another group | The inventory line is from an earlier VM, or from this VM before its address or system changed | Nothing changed. Check which VM the line describes. When that VM is gone, remove the line and the old key as [rebuild or retire a target](#do-rebuild-or-retire-a-target) shows, then run `add-target.sh` again. |
| `add-target.sh` says `Missing inventory or known-hosts file` | Another lab folder than `/opt/ansible-lab`, or the controller was not made by the installer | Add `--lab-dir DIR`; on a controller set up by hand, follow [manual access](manual-access.md) instead. |
| Ping fails with `Host key verification failed`, or `add-target.sh` says `NAME (ADDRESS) is in ..., but known-hosts holds a different key` | The VM was rebuilt or restored at the same address and has new host keys | Read its lines again, with `inventory-info.sh` or by preparing it again after a rebuild, and run `add-target.sh --from-info` with them. After verifying why the key changed, run the two commands it prints, then run it once more: it trusts the new key and keeps the inventory line. |
| Ping fails with `Permission denied (publickey)` | `svc_ansible` lacks the service key, the controller was reinstalled with a new key, or an `AllowUsers`/`AllowGroups` rule leaves the account out | Compare `sudo ssh-keygen -lf /home/svc_ansible/.ssh/authorized_keys` on the VM with `ssh-keygen -lf ~/svc_ansible.pub` on the controller; run the Stage 2 onboarding again with the right key. |
| Ping or Baseline fails for every host while only one is broken | The lessons stop all hosts when one fails, and an unreachable host fails the run | Fix or retire the broken host, then run again. |
| Baseline preview says `Missing sudo password` | Semaphore has no sudo password for the inventory | [Give Semaphore the sudo password](#do-give-semaphore-the-sudo-password). |
| A task fails with `Destination /etc not writable`, or similar only when something must change | **Lab sudo** has a Username | Edit the key and leave Username empty. |
| `Incorrect sudo password`, or the account is locked after several tries | Semaphore's password differs from the VM's, for example one shared credential for targets whose passwords differ; after a vendor STIG, `faillock` locks the account after three failures | Fix the password in Semaphore, or give each target its own with Vault. Reset the lock at the VM's console as its administrator with `sudo faillock --user svc_ansible --reset`, or through Azure Run Command. |
| Semaphore says `Permission denied` reading a host variables file | The file is not in the `semaphore` group | Run the `chgrp` and `chmod` from the per-target way again. |

[Troubleshooting](11-troubleshooting.md) covers the rest, in the same order
as the layers: network, SSH, sudo, then Semaphore.

## Concept

The seeded repository is the lab folder itself, and its inventory is a file
read at run time. There is nothing to sync and nothing cached: the file is the
truth, and so is a half-edited file. The service also reads the folder's
current contents, uncommitted edits included. The folder's `.gitignore` keeps
`inventories/` out of Git, so Git cannot show or undo an inventory edit: copy
`lab.ini` aside before editing it by hand, and rely on
[chapter 10](10-recovery.md)'s capture of the lab folder for recovery. Edit
playbooks as the lab folder's owner and keep the service's group read access.
When you want tasks to run only reviewed, pushed code, follow
[moving the lab folder to Git](appendices/git-migration.md); it explains why
**Lab inventory file** stays bound to the local folder.

## Next

The target is onboarded. Go further, in this order:

1. [Command-line lessons](05-cli-lessons.md): the same playbooks from the
   terminal. On the installed controller, work in `/opt/ansible-lab`, whose
   `ansible.cfg` reads this inventory. The terminal needs a key of your own
   on each target, listed beside the service key when you onboard it, as
   [Stage 2](stage-2-existing-machines.md#do-run-the-onboarding-script-over-ssh)
   shows; with per-target Vault passwords, add `--ask-vault-pass` and leave
   out `-K`.
2. [Semaphore's objects](06-semaphore.md): what the seeded project, key,
   inventory, repository and templates are, and how to build them by hand.
3. [Git and VS Code](07-git-and-vscode.md).
4. [Recovery](10-recovery.md), before you change anything you cannot rebuild.
5. [Operations](08-operations.md) and the
   [security benchmarks](09-security-benchmarks.md), whose seeded STIG
   templates need the recovery preparation first.
6. [The learning path](12-learning-path.md).

[Go further](../README.md#go-further) on the front page lists the rest.
