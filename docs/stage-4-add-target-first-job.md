# Stage 4: add the target and run the first job

[Back to the guide](../README.md) · [Previous: Stage 2, existing machines](stage-2-existing-machines.md) or [Stage 3, new VMs](stage-3-new-vms-cloud-init.md) · [Next: go further](../README.md#go-further)

## Goal

The controller's lab inventory lists the target, the service trusts its
verified host key, Semaphore has the targets' sudo password, and the seeded
**Ping** and **Baseline preview** templates succeed for it. The target is then
onboarded, and every lesson in the guide can run against it.

**Which steps you need.** A machine you onboarded with
[Stage 2's one command](stage-2-existing-machines.md#do-onboard-it-in-one-command-from-the-controller),
`controller/onboard-target.sh`, is already in the inventory with its verified
host key: start at
[give Semaphore the sudo password](#do-give-semaphore-the-sudo-password).
Every other machine needs the first step, `add-target.sh`, too: a VM that
cloud-init prepared in Stage 3, and a machine prepared by the script over SSH
or at the console, by the bootstrap playbook, or through Azure.

## Before you start

- **The controller from Stage 1,** with the **Ansible Automation** project the
  installer seeded. Its inventory, **Inventory file**, is the local file
  `/opt/ansible-lab/inventories/lab.ini`, empty at first. Do not recreate the
  project, and do not set up a Git host to run these templates.
- **The guide's folder** on the controller, `~/ansible-semaphore-guide`: the
  copy of the guide you installed from, or the newer one you updated with. It
  is not the lab folder `/opt/ansible-lab`. `add-target.sh` runs from the
  guide's folder.
- **From Stage 2 or Stage 3, for each target not added by the one command:**
  the `name=`, `address=`, `group=` and `fingerprint=` lines, or, after the
  bootstrap playbook, the whole `add-target.sh` command it printed.
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
Lines from cloud-init are accepted as they are: with `onboard:` in front, and
with a console or journal stamp such as `[   83.117215] cloud-init[1026]: `
before that. Then
press Enter, so the cursor is on a new line, and press Ctrl-D. Ctrl-C and then
Ctrl-D cancels without changing anything. Success looks like this:

```text
Using name=lab-alma address=alma.example.test group=enterprise_linux fingerprint=SHA256:...
Added lab-alma (alma.example.test) to /opt/ansible-lab/inventories/lab.ini under [enterprise_linux] and trusted its verified host key.
Next: run the Ping template, which covers every host in the lab group. If lab-alma fails with Permission denied (publickey),
svc_ansible on lab-alma lacks the key 'sudo cat /etc/semaphore/svc_ansible.pub' shows; if sudo asks for a
password, give Semaphore the targets' sudo password: sudo python3.12 controller/lab-sudo.py
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

**Where: the controller, as your administrator account, in the guide's
folder; once per password.** The seeded inventory has no sudo credential.
Until you add one, every template that uses sudo, which is all of them except
**Ping** and **Health report**, stops with `Missing sudo password`.

**One shared sudo password, the default.** If every lab target has the same
`svc_ansible` sudo password, as Stage 2 recommends, give it to Semaphore with
[`controller/lab-sudo.py`](../controller/lab-sudo.py):

```bash
cd ~/ansible-semaphore-guide
sudo python3.12 controller/lab-sudo.py
```

It logs in to Semaphore first, as `admin` with the installer's password. You
changed that password in Stage 1, so it says so and asks for your Semaphore
administrator's login and its current password. Then it asks for the sudo
password twice. Nothing you type is shown:

```text
The installer's admin password is missing or no longer logs in (changed in the UI?).
Semaphore administrator login [admin]:
Password:
Sudo password of svc_ansible on the lab targets:
The same password again:
Stored the targets' sudo password as the key 'Target sudo password' (ID 3), with an empty Username, and chose it as the Sudo Credentials of 'Inventory file'.
Next: run the Baseline preview template. Every lab target needs this same sudo password for svc_ansible.
```

The ID is your own. Through Semaphore's API on loopback, it stores the
password as the key **Target sudo password**, of the type **Login with password** and with
an empty **Username**, and chooses that key as the **Sudo Credentials** of
**Inventory file**. The password goes only to Semaphore and is never
printed. It warns about a password shorter than 12 characters, which the
onboarding script and the bootstrap playbook cannot give to a target.

At `Semaphore administrator login [admin]:`, Enter alone means `admin`. An
administrator with a second factor cannot log in this way: give an API token
instead, as [updating a controller](controller-update.md#options-and-logins)
explains, with
`sudo --preserve-env=SEMAPHORE_API_TOKEN python3.12 controller/lab-sudo.py`.

Running it again changes nothing and says that **Inventory file** already
uses **Target sudo password**. To change the password later, after you changed it on
every target, store the new one in the same key:

```bash
sudo python3.12 controller/lab-sudo.py --replace
```

It refuses, with what to do and `Nothing was changed.`, when the inventory
already uses another key as its sudo credential, when a key named **Target sudo password**
has another type, or when two keys share that name. Other
options: `--lab-dir DIR` for another lab folder, `--project-id ID` when
several projects are named **Ansible Automation**, and `--password-stdin` to read
the password from one line of standard input in a script. It exits with
status 0 on success, 1 when it refuses or fails, and 2 for an unknown option.

**Or in the UI.** The same two steps by hand:

1. Open **Key Store → New Key**. Name it **Target sudo password**, choose the type
   **Login with password**, leave **Username empty**, and enter the sudo
   password as **Password**. Save.
2. Open **Inventory → Inventory file**, select **Target sudo password** as **Sudo
   Credentials**, and save.

Leave the Username empty. Semaphore passes it to Ansible as `--become-user`,
the account to become, so `svc_ansible` there would make every privileged task
run as `svc_ansible` instead of root: runs that change nothing still look
green, and the first real change fails with an error such as
`Destination /etc not writable`. Semaphore never shows a key's Username again,
so `lab-sudo.py` cannot see one typed in the UI; when you are not sure, run
`sudo python3.12 controller/lab-sudo.py --replace`, which stores the password
anew with an empty Username. One inventory holds one sudo credential, which
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

**Where: Semaphore, the Baseline tab of the Ansible Automation project.** Start a
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

**Then the Operations tab.** Run **Health report**, the next thing to run on
a new target and at the start of any later session. It reads each host in
`lab` without sudo, changes nothing, and ends with one line per host:

```text
ok: [lab-alma] => {
    "msg": [
        "lab-alma: AlmaLinux 9.8, kernel 5.14.0-687.61.1.el9_8.x86_64, up 0 d 1 h 12 min",
        "Root file system: 9% used, 36211 MiB free of 40140 MiB. Memory: 21% used, 2296 MiB available of 2916 MiB.",
        "Failed systemd units: 0",
        "Reboot pending: no",
        "Time: synchronized",
        "Pending package updates: none"
    ]
}
...
ok: [lab-alma] => {
    "msg": "lab-alma: OK"
}
```

A host that needs a look says `needs attention:` and why, for example
`lab-alma: needs attention: reboot pending; 12 package update(s) pending`.
[The runbooks](runbooks.md#check-every-machines-health) explain each line.

The natural next step continues on the **Baseline** tab:

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

**Where: the controller, as your administrator account, in the guide's
folder.**

**To retire a target, or give its address to another VM,** remove it with
[`controller/remove-target.sh`](../controller/remove-target.sh), the inverse
of `add-target.sh`:

```bash
cd ~/ansible-semaphore-guide
sudo bash controller/remove-target.sh --name lab-alma
```

```text
Removed lab-alma ansible_host=alma.example.test from /opt/ansible-lab/inventories/lab.ini; the inventory as it was is in /opt/ansible-lab/inventories/lab.ini.before-remove-lab-alma.20261110T143012.bak.
Removed 1 trusted host key line(s) for alma.example.test from /etc/semaphore/known_hosts:
  SHA256:... (RSA)
Only the controller changed: lab-alma itself still has the svc_ansible account, its authorized keys, its sudo rule and its SSH drop-in.
```

It removes the line `NAME ansible_host=ADDRESS` that `add-target.sh` wrote,
keeps the inventory as it was beside it, as
`lab.ini.before-remove-NAME.YYYYmmddTHHMMSS.bak`, and removes every line that
the service's known-hosts file holds for that address, plain or hashed. Both
files keep their owner, group and mode, so the service can still read them;
what changes in the lab folder is done as that folder's owner, never as root.
A `host_vars` file for the name stays, and the last lines name it, because a
later host of that name would get its variables. It
keeps the host key when you pass `--keep-key`, or when another inventory host
uses the same address. A name that is not in the inventory changes nothing and
says `NAME is not in FILE; nothing changed.`, so running it again is safe. It
refuses, changing nothing, a group's name, a name listed on several lines, a
line with other settings than `add-target.sh` writes, a file that is a link,
and a known-hosts line that names the address among other hosts; those are
for editing by hand. `--lab-dir DIR` and `--known-hosts FILE` name other files
than `/opt/ansible-lab` and `/etc/semaphore/known_hosts`.

By hand, it does what these commands do, the first two as the lab folder's
owner:

```bash
cp /opt/ansible-lab/inventories/lab.ini ~/lab.ini.before-retire
sed -i '/^lab-alma /d' /opt/ansible-lab/inventories/lab.ini
sudo ssh-keygen -R alma.example.test -f /etc/semaphore/known_hosts
sudo chown root:semaphore /etc/semaphore/known_hosts && sudo chmod 0640 /etc/semaphore/known_hosts
```

`ssh-keygen -R` rewrites the file as `root:root`; without the `chown` the
service can no longer read it, and every job fails host verification.
`sudo python3.12 controller/check-controller.py`, run in the guide's folder,
reports this as `service_can_read_known_hosts`.

**The machine itself keeps the account.** Retiring changes only the
controller. When the machine stays in use and should no longer let the
controller in, undo by hand, as its administrator, what the onboarding
created. There is no script for this. Stop any process of the account, delete
the account only if the onboarding created it (`account: svc_ansible created`
in its first output), then remove the sudo rule and the SSH drop-in and check
both configurations before SSH reloads:

```bash
sudo loginctl terminate-user svc_ansible
sudo pkill -KILL -u svc_ansible
sudo userdel -r svc_ansible
sudo rm /etc/sudoers.d/90-ansible-lab
sudo visudo -c
sudo rm /etc/ssh/sshd_config.d/70-ansible-lab.conf
sudo sshd -t
sudo systemctl reload ssh
```

On Enterprise Linux, reload `sshd` in place of `ssh`. The first two lines end
the account's sessions, such as a connection the controller still holds open;
`loginctl` complains when the account is not logged in, and `pkill` prints
nothing and returns 1 when it runs nothing. If `userdel` says the account
`is currently used by process`, its processes are still ending: wait a few
seconds and run that line again. On Ubuntu it also notes that there is no mail
spool, which is harmless. Also on Ubuntu, at the console of a machine nobody
has connected to since it started, the SSH service is not running yet:
`sshd -t` then misses `/run/sshd`, so run `sudo mkdir -p /run/sshd` first, and
the reload answers that the unit is not active, which needs nothing, because
the service reads the configuration when the next connection starts it. Leave
out `userdel` for an
account that existed before the onboarding; then remove its
`~svc_ansible/.ssh/authorized_keys` instead, which holds the service key.


**A rebuilt or restored target at the same address** presents new host keys.
Your own `~/.ssh/known_hosts` and the service's known-hosts file both still
trust the old ones. After you have confirmed at the console why the key
changed, forget the old key in both places, then onboard the machine again:

```bash
ssh-keygen -R alma.example.test
sudo bash controller/remove-target.sh --name lab-alma
bash controller/onboard-target.sh ADMIN@alma.example.test
```

The last command asks SSH's host-key question again: compare with the console
as [Stage 2](stage-2-existing-machines.md#do-onboard-it-in-one-command-from-the-controller)
shows. For a VM that cloud-init prepared again, or a machine you prepare by
hand, run `add-target.sh` with its new lines instead of the last command. Without
`remove-target.sh`, `add-target.sh` finds the host in the inventory and a
different key trusted for its address, changes nothing, and prints the
commands that remove the old key, the `ssh-keygen -R` and `chown` lines above;
run them, then run `add-target.sh` once more with the same lines. It checks the
new key against the fingerprint as before, adds no second inventory line, and
says:

```text
Trusted the verified host key of lab-alma (alma.example.test), which /opt/ansible-lab/inventories/lab.ini already lists.
```

**A rebuilt or reinstalled controller** has a new service key pair, unless
you restored `/etc/semaphore` from [chapter 10](10-recovery.md). Every target
still authorizes the old public key, so the new key cannot log in. Unless you
restored the lab folder and Semaphore from chapter 10, the new controller's
inventory, its known-hosts file and Semaphore's Key Store are empty as well.
Run [Stage 2's one command](stage-2-existing-machines.md#do-onboard-it-in-one-command-from-the-controller)
again for every target: it reads the new service key, replaces the account's
authorized keys with it, and adds the target again. Type the same shared
password when it asks, or pass `--keep-password` to keep each account's
password. Then
[give Semaphore the sudo password](#do-give-semaphore-the-sudo-password)
again with `lab-sudo.py`. The script and the playbook of Stage 2 also replace
the authorized keys with exactly the ones you give them, when you onboard by
hand.

## Check

On the controller, the inventory lists the target, and the service trusts a key
for its address:

```bash
grep -n '^[^#]*ansible_host' /opt/ansible-lab/inventories/lab.ini
sudo ssh-keygen -F alma.example.test -f /etc/semaphore/known_hosts
cd ~/ansible-semaphore-guide
sudo python3.12 controller/check-controller.py
```

The readiness report ends with `"passed": true`. In Semaphore, the **Lab
inventory file** shows **Target sudo password** as its **Sudo Credentials**, or every
template lists **Lab vault password** under **Vaults**. **Ping** and
**Baseline preview** succeed for the new host, and Ping names its
distribution. The target is onboarded.

## Save these values

| Value | Where it came from | Needed for |
| --- | --- | --- |
| The target's inventory name and address | `add-target.sh`'s `Added` line | `--limit` in later lessons; retiring it |
| The **Target sudo password** password, or each target's | Stage 2 or 3; already in your password manager | Recovery, and every new target with the shared password |
| The Vault password, if you chose per-target passwords | You chose it at `ansible-vault create` | Every edit of the host files; the command-line lessons |

## When a step fails

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| `add-target.sh` refuses the pasted lines | A line is missing because the VM could not read its value, or its hostname is one the inventory reserves; a line appears twice; a value is also given as an option; a value is not a plain name, address or fingerprint; or the name is `localhost`, `all`, `ungrouped` or an inventory group's, such as `lab`, `ubuntu` or `enterprise_linux` | Nothing changed. Give the value `add-target.sh` says is missing with the option it names (`--name`, `--address` or `--fingerprint`). For a refused name, paste the lines again without the `name=` line and add `--name NAME`, as its message says. Paste one VM's lines at a time, and read a refused value again at the VM's console, or with [`inventory-info.sh`](stage-2-existing-machines.md#do-read-a-prepared-vms-values-again). |
| `add-target.sh` says `No SSH host key received from ADDRESS` | The controller cannot reach the VM's SSH port at that address | Nothing changed. Check the address, that the VM is running and its SSH service active, and every firewall between them: `firewalld` or `ufw` on the VM, the hypervisor's firewall, such as Proxmox's, a VLAN or routing rule, or a cloud security group, such as the Azure targets' group, which admits SSH only from `azure_target_ssh_source`. From the controller, `ssh-keyscan -t rsa ADDRESS` should print the VM's key. |
| `add-target.sh` says `No scanned key matched` | The fingerprint is from another VM, was mistyped, or the VM was rebuilt | Read the fingerprint again at the VM's console; never take it from the scan. |
| `add-target.sh` says `Known-hosts already contains a different key` | The address belonged to an earlier VM | Verify why, then follow the commands it prints to remove the old key. |
| `add-target.sh` says `Inventory already lists ADDRESS as NAME`, `Inventory already contains NAME with other settings`, or that the inventory lists the name under another group | The inventory line is from an earlier VM, or from this VM before its address or system changed | Nothing changed. Check which VM the line describes. When that VM is gone, remove its line and its old key with `sudo bash controller/remove-target.sh --name NAME`, as [rebuild or retire a target](#do-rebuild-or-retire-a-target) shows, then run `add-target.sh` again. A machine that is in the inventory under an earlier name is not an error when the name came from the machine, the group is the same and its key is the trusted one: `add-target.sh --from-info` then says `Already present as NAME` and changes nothing. |
| `add-target.sh` says `Missing inventory or known-hosts file` | Another lab folder than `/opt/ansible-lab`, or the controller was not made by the installer | Add `--lab-dir DIR`; on a controller set up by hand, follow [manual access](manual-access.md) instead. |
| Ping fails with `Host key verification failed`, or `add-target.sh` says `NAME (ADDRESS) is in ..., but known-hosts holds a different key` | The VM was rebuilt or restored at the same address and has new host keys | After verifying at the console why the key changed, follow [rebuild or retire a target](#do-rebuild-or-retire-a-target): `remove-target.sh`, then onboard it again. Or read its lines again, with `inventory-info.sh` or by preparing it again, run `add-target.sh --from-info` with them, run the two commands it prints, then run it once more: it trusts the new key and keeps the inventory line. |
| Ping fails with `Permission denied (publickey)` | `svc_ansible` lacks the service key, the controller was reinstalled with a new key, or an `AllowUsers`/`AllowGroups` rule leaves the account out | Compare `sudo ssh-keygen -lf /home/svc_ansible/.ssh/authorized_keys` on the VM with `sudo ssh-keygen -lf /etc/semaphore/svc_ansible.pub` on the controller; run [Stage 2's one command](stage-2-existing-machines.md#do-onboard-it-in-one-command-from-the-controller) again, which gives the account the controller's current key. |
| Ping or Baseline fails for every host while only one is broken | The lessons stop all hosts when one fails, and an unreachable host fails the run | Fix or retire the broken host, then run again. |
| Baseline preview says `Missing sudo password` | Semaphore has no sudo password for the inventory | [Give Semaphore the sudo password](#do-give-semaphore-the-sudo-password): `sudo python3.12 controller/lab-sudo.py`. |
| A task fails with `Destination /etc not writable`, or similar only when something must change | **Target sudo password** has a Username | `sudo python3.12 controller/lab-sudo.py --replace` stores the password anew with an empty Username. |
| `Incorrect sudo password`, or the account is locked after several tries | Semaphore's password differs from the VM's, for example one shared credential for targets whose passwords differ; after a vendor STIG, `faillock` locks the account after three failures | Reset the lock at the VM's console as its administrator with `sudo faillock --user svc_ansible --reset`, or through Azure Run Command, before the next run. Then make the two agree: `sudo python3.12 controller/lab-sudo.py --replace` with the targets' password, or give each target its own with Vault. [The runbooks](runbooks.md#svc_ansible-is-locked-out-after-hardening) have the sequence. |
| `lab-sudo.py` says `'Inventory file' already uses the key ... as its Sudo Credentials, not 'Target sudo password'` | The inventory already has another sudo credential, such as one you made by hand | Nothing changed. Choose **Target sudo password** under **Inventory → Inventory file → Sudo Credentials** in the UI, or empty that field and run it again. |
| `lab-sudo.py` says `The key 'Target sudo password' (ID N) has the type ...` or `N keys are named 'Target sudo password'` | A key of another type, or a second key, has that name | Nothing changed. Rename or delete the extra key in **Key Store**, then run it again. |
| `lab-sudo.py` says `The installer's admin password is missing or no longer logs in` and the login it asks for is refused | The administrator's password was mistyped, or it uses a second factor | Type the current password, or give an API token with `SEMAPHORE_API_TOKEN`, as [updating a controller](controller-update.md#options-and-logins) explains. |
| `lab-sudo.py` says `semaphore.service is not running; start it first.` | Semaphore is stopped | `sudo systemctl start semaphore`, then run it again. |
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
**Inventory file** stays bound to the local folder.

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
