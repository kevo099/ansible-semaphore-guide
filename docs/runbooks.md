# Runbooks: common tasks

[Back to the guide](../README.md) · [The whole path as one flowchart](ONBOARDING.md)

Short recipes for the tasks that come up once the lab runs. Each one says when
to use it, what to do, how to check it, and how to undo it or what comes next,
and links to the page that explains it. They assume an installed controller
from [Stage 1](stage-1-controller.md), the guide's folder
`~/ansible-semaphore-guide`, the lab folder `/opt/ansible-lab` and one shared
sudo password for the lab targets. Commands on the controller run as your
administrator account in the guide's folder; add `--lab-dir DIR` where you
installed with it.

## Onboard one existing machine

**When:** a supported Linux machine runs, and the controller can log in to it
over SSH as its administrator.

**Do:** on the controller,

```bash
cd ~/ansible-semaphore-guide
bash controller/onboard-target.sh ADMIN@VM_ADDRESS
sudo python3.12 controller/lab-sudo.py
```

Type the shared sudo password when the first command asks, and compare the
host key with the machine's console before you answer SSH's question. The
second command is needed once for the lab: skip it when Semaphore already holds
that password. Then, in Semaphore, run **Ping** and **Baseline preview** on the
**Lessons** tab, and **Health report** on the **Operations** tab.
[Stage 2](stage-2-existing-machines.md#do-onboard-it-in-one-command-from-the-controller)
explains every prompt. The command makes the controller's service key the
account's only login; to log in as `svc_ansible` with your own key too, for
the command-line lessons, add `--extra-key ~/.ssh/ansible_lab.pub`, on every
run for that machine.

**Check:** the command ends with `Prepared and in the inventory: ADMIN@VM_ADDRESS`;
Ping and Baseline preview show `failed=0` for the new host; the Health report
ends with `NAME: OK`.

**Undo or next:** [retire the target](#retire-a-target). Without SSH from the
controller, use [the console way](stage-2-existing-machines.md#do-run-the-onboarding-script-from-the-console)
and [add it with `add-target.sh`](stage-4-add-target-first-job.md#do-add-the-target-with-add-targetsh).

## Onboard several machines at once

**When:** several running machines share the lab's sudo password, and the
controller can log in to each one as its administrator.

**Do:** name them all in one run; the password is asked once:

```bash
cd ~/ansible-semaphore-guide
bash controller/onboard-target.sh ADMIN@VM_ADDRESS_1 ADMIN@VM_ADDRESS_2 ADMIN@VM_ADDRESS_3
```

Each machine asks its own host-key question. A machine whose hostname the
inventory reserves needs a run of its own with `--name NAME`.

**Check:** the last lines list `Prepared and in the inventory:` and, if any
machine failed, `Not finished:`; the run then exits with status 1. Run
**Ping** once: it covers every host in `lab`.

**Undo or next:** run the command again for the machines under
`Not finished`, after fixing what their section of the output names, as
[Stage 2](stage-2-existing-machines.md#do-onboard-it-in-one-command-from-the-controller)
shows. A run again for a finished machine is safe.

## Pre-deploy a batch of VMs on Proxmox from a template

**When:** you will create several new VMs on Proxmox and want each one ready
at its first boot.

**Do:**

1. On the controller, make the filled cloud-init file, with the password's
   hash so that the VMs need no step after boot, as
   [Stage 3](stage-3-new-vms-cloud-init.md#optional-let-the-file-set-the-sudo-password)
   explains the trade-off:

   ```bash
   cd ~/ansible-semaphore-guide
   (umask 077 && bash onboard/new-vm/fill-cloud-init.sh --with-password ~/svc_ansible.pub > ~/onboard-new-vm.yaml)
   ```

   Leave out `--with-password` for a file without a secret; then set each
   VM's password after its boot.
2. Copy it to the node's snippets and make it private there, as
   [Stage 3, step 2](stage-3-new-vms-cloud-init.md#do-on-proxmox-attach-the-file-to-a-new-vm)
   shows; on the node, `chmod 600 /var/lib/vz/snippets/onboard-new-vm.yaml`.
3. On the node, build one VM as Stage 3, steps 3 to 5, show, with the file as
   vendor data, **do not start it**, and turn it into a template:

   ```bash
   qm template TEMPLATE_VMID
   ```

4. For each new VM, clone the template, give the clone its own name (and its
   own address with `qm set NEW_VMID --ipconfig0 ...` if you use fixed ones),
   start it and watch its console; Ctrl-O leaves the console:

   ```bash
   qm clone TEMPLATE_VMID NEW_VMID --name NAME
   qm start NEW_VMID
   qm terminal NEW_VMID
   ```

5. On the controller, add each VM from the `onboard:` lines its console
   printed, one VM per run, pasting at the prompt and pressing Ctrl-D:

   ```bash
   sudo bash controller/add-target.sh --from-info
   ```

6. Give Semaphore the shared password once, if it does not hold it yet:
   `sudo python3.12 controller/lab-sudo.py`.

**Check:** each console shows
`onboard: svc_ansible is ready, with its sudo password set` (without the hash:
`... ready; set its sudo password next`); each `add-target.sh` run says
`Added NAME ...`; **Ping**, **Baseline preview** and **Health report** pass
for every new host.

**Undo or next:** [retire](#retire-a-target) a clone you no longer want, then
delete it in Proxmox. Without the hash, set each VM's password as
[Stage 3](stage-3-new-vms-cloud-init.md#do-set-the-sudo-password) shows, or,
when the VM's administrator accepts a key of the controller's, run
`bash controller/onboard-target.sh ADMIN@VM_ADDRESS` for it, which sets the
password and adds it in one step.

## Give or change the lab's sudo password

**When:** Semaphore does not hold the targets' sudo password yet, or you want
a new shared password for every target.

**Do:** to give Semaphore the password the targets already have:

```bash
cd ~/ansible-semaphore-guide
sudo python3.12 controller/lab-sudo.py
```

To change it, first pause any [schedule](16-semaphore-operations.md) and
start no Semaphore task until both commands below are done: the targets and
Semaphore disagree in between, and on a STIG-hardened target three wrong sudo
passwords lock the account. Then set the new password on every target, by
running the one command again for all of them and typing the new password,
and store it in Semaphore:

```bash
cd ~/ansible-semaphore-guide
bash controller/onboard-target.sh ADMIN@VM_ADDRESS_1 ADMIN@VM_ADDRESS_2
sudo python3.12 controller/lab-sudo.py --replace
```

If you gave a machine `--extra-key FILE` before, give it again here, in a run
for that machine: the one command sets the account's keys anew each time. A
target the controller cannot log in to gets the new password at its console
with `sudo passwd svc_ansible`. Save the new password in your password
manager, and resume the schedules.

**Check:** `lab-sudo.py` says `Stored the new password in the key 'Lab sudo'
(ID N), with an empty Username`; **Baseline preview** passes for every host.

**Undo or next:** run both commands again with the old password. The details
are in [Stage 4](stage-4-add-target-first-job.md#do-give-semaphore-the-sudo-password).

## Check every machine's health

**When:** at the start of a session, before patching, after a reboot, or
whenever a target seems slow or full.

**Do:** in Semaphore, on the **Operations** tab, run **Health report**. It
runs on every host in `lab`, uses no sudo, changes nothing (its recap always
shows `changed=0`), and needs no sudo password in Semaphore.

**Check:** it gives two outputs per host. The first is a list of lines:

- the inventory name, system and version, kernel, and uptime;
- the root file system's use and free space, and memory use and available
  memory, in MiB;
- `Failed systemd units:` the count and up to five names, or `unknown` when
  `systemctl` could not list them;
- `Reboot pending: no`, `yes` or `unknown`. Ubuntu reports the
  `/var/run/reboot-required` marker; Enterprise Linux compares the running
  kernel with the newest installed one and names both when they differ;
- `Time:` `synchronized`, `not synchronized` with the state of the time
  service, or `unknown`;
- `Pending package updates:` `none`, a number, or
  `not checked; the local package data could not be read without sudo`. The
  count reads only the package data already on the host and downloads
  nothing, so it is as fresh as the host's last package-list update.

The second is one line, `NAME: OK`, or `NAME: needs attention:` followed by
every reason: the root file system or memory at 90 % or more, failed units,
a pending or unknown reboot, a clock that is not synchronized, or pending
updates. A host that cannot be read at all fails the run; the others still
report.

**Undo or next:** nothing to undo. Act on what it names:
[patching](08-operations.md#patching-one-target-at-a-time) for updates and a
pending reboot, [reboot one target](#reboot-one-target-safely), or
[troubleshooting](11-troubleshooting.md) for failed units.

## Reboot one target safely

**When:** a target must restart, for example after the Health report says
`reboot pending`, and nobody depends on it for the next minutes.

**Do:** in Semaphore, on the **Operations** tab, run **Reboot one target**.
In the Run dialog, type exactly one inventory host in **Limit**, such as
`lab-alma`, and choose `REBOOT NOW - restart this one target`. Turn on **Dry
Run** first for a preview: it reads the target, reports its boot ID, uptime
and failed units, and reboots nothing. It needs **Lab sudo**. From the
terminal, set up as [chapter 5](05-cli-lessons.md#establish-the-command-line-environment)
shows and with a key of your own authorized for `svc_ansible`, the same is
`ansible-playbook playbooks/reboot.yml --limit lab-alma --private-key ~/.ssh/ansible_lab -K -e '{"reboot_confirm": true}'`.

**Check:** the log ends with the target's boot ID before and now, which must
say `changed`, its uptime, its system state, and its failed units now and
before the reboot. It waits up to 15 minutes for the target to answer again.
A Limit with several hosts, or no choice in the dialog, is refused with
`Nothing was changed.` So is the controller itself, should it be in the
inventory: its reboot would stop Semaphore in the middle of the task, so
restart it from its own terminal when no task runs.

**Undo or next:** a reboot cannot be undone. If the target does not answer
again, open its console. Run **Health report** afterwards;
[chapter 8](08-operations.md#reboot-explicitly) has the checks of the
applications themselves.

## Retire a target

**When:** a target is gone for good, or its address goes to another VM.

**Do:** on the controller,

```bash
cd ~/ansible-semaphore-guide
sudo bash controller/remove-target.sh --name NAME
```

**Check:** it says `Removed NAME ansible_host=ADDRESS from ...`, names the
backup of the inventory and the host-key lines it removed, and ends with
`Only the controller changed: ...`. **Ping** no longer lists the host.

**Undo or next:** the inventory as it was is in
`/opt/ansible-lab/inventories/lab.ini.before-remove-NAME.YYYYmmddTHHMMSS.bak`;
to bring the target back, onboard it again. The machine keeps `svc_ansible`,
its keys, its sudo rule and its SSH drop-in; to remove them by hand, see
[Stage 4](stage-4-add-target-first-job.md#do-rebuild-or-retire-a-target).

## A target was rebuilt or shows a changed host key

**When:** **Ping** fails with `Host key verification failed`, `add-target.sh`
says that known-hosts holds a different key, or SSH says
`REMOTE HOST IDENTIFICATION HAS CHANGED`, after a rebuild, a restore or a
change to a VM's cloud-init settings.

**Do:** first confirm at the machine's console why the key changed, with
`sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub`. A change you cannot
explain means another machine may answer at that address: stop there. When
you know why, on the controller:

```bash
cd ~/ansible-semaphore-guide
ssh-keygen -R VM_ADDRESS
sudo bash controller/remove-target.sh --name NAME
bash controller/onboard-target.sh ADMIN@VM_ADDRESS
```

**Check:** the last command ends with `Prepared and in the inventory:`, and
**Ping** passes for the host.

**Undo or next:** [Stage 4](stage-4-add-target-first-job.md#do-rebuild-or-retire-a-target)
shows the same with `add-target.sh`, for a VM that cloud-init prepared again.

## The controller was rebuilt

**When:** the controller was reinstalled, so it has a new service key, and the
targets refuse it with `Permission denied (publickey)`.

**Do:** either restore the old controller's files from your capture, as
[chapter 10](10-recovery.md#restore-first-into-an-isolated-replacement)
shows, which keeps the old key and needs nothing on the targets; or give every
target the new key and add it again:

```bash
cd ~/ansible-semaphore-guide
bash controller/onboard-target.sh ADMIN@VM_ADDRESS_1 ADMIN@VM_ADDRESS_2
sudo python3.12 controller/lab-sudo.py
```

Type the lab's sudo password when the first command asks, or pass
`--keep-password` to keep each account's own.

**Check:** **Ping**, **Baseline preview** and **Health report** pass for
every host.

**Undo or next:** [Stage 4](stage-4-add-target-first-job.md#do-rebuild-or-retire-a-target)
explains why every target needs the new key.

## Update the controller to a new release

**When:** a newer release of the guide is out, and the controller was made by
one of its installers.

**Do:** on the controller, as [update a controller](controller-update.md)
explains:

```bash
cd ~/ansible-semaphore-guide
git status --short
git fetch --tags origin
git checkout RELEASE_TAG
sudo bash controller/update-controller.sh
sudo bash controller/update-controller.sh --apply
```

Read the plan that the first `update-controller.sh` prints before you run the
second. When its last lines say the Ansible runtime or Semaphore's SSH
settings are older too, which happens on a controller installed before
`v1.8.0`, update those while no task runs:

```bash
sudo bash controller/update-runtime.sh
sudo bash controller/update-runtime.sh --apply
```

To bring machines you added with an earlier release to today's account
standard, under the names they already have:

```bash
bash controller/onboard-target.sh ADMIN@VM_ADDRESS ADMIN@OTHER_ADDRESS --keep-password
```

**Check:** the update ends with `Updated to RELEASE_TAG. The readiness check
passed.`, the runtime update with `Updated. The readiness check passed.`, the
onboarding with `Already present as NAME` for each machine, and **Ping** still
succeeds.

**Undo or next:** `git revert HEAD` in the lab folder undoes the files, not
the Semaphore changes, as
[the update page](controller-update.md#do-apply-the-update) explains.

## Get a target's values again

**When:** you need a prepared machine's `name=`, `address=`, `group=` and
`fingerprint=` lines again, for example to add it with `add-target.sh`.

**Do:** copy [`onboard/inventory-info.sh`](../onboard/inventory-info.sh) to the
machine and run it there with root rights, then delete it:

```bash
cd ~/ansible-semaphore-guide
scp onboard/inventory-info.sh ADMIN@VM_ADDRESS:
ssh -t ADMIN@VM_ADDRESS 'sudo sh inventory-info.sh; rm inventory-info.sh'
```

**Check:** it prints the four lines after a short summary, or stops with
`INFO FAILED:` and names the constant at its top to fill in.

**Undo or next:** it changes nothing. Without SSH, run it at the console as
[Stage 2](stage-2-existing-machines.md#do-read-a-prepared-vms-values-again)
shows.

## `svc_ansible` is locked out after hardening

**When:** after a vendor STIG, sudo for `svc_ansible` fails even with the right
password, or tasks say `Incorrect sudo password` until the account locks:
`pam_faillock` locks it after three wrong passwords within 15 minutes, and
the STIG sets no automatic unlock.

**Do:** on the target, at its console or over SSH as its administrator, see
the failures and reset the lock:

```bash
sudo faillock --user svc_ansible
sudo faillock --user svc_ansible --reset
```

Then make the target and Semaphore agree, before the next task. When you are
not sure which password the target has, set the shared one again there, as an
administrator who can still use `sudo` or at a root console:

```bash
sudo passwd svc_ansible
```

When Semaphore holds the wrong one, store the right one, on the controller:

```bash
cd ~/ansible-semaphore-guide
sudo python3.12 controller/lab-sudo.py --replace
```

`controller/onboard-target.sh` sets the password too, but only while the
target's administrator can still log in over SSH and use `sudo`; a vendor STIG
can take both away, as [chapter 9](09-security-benchmarks.md) describes, and
then the console is the way in.

**Check:** `sudo faillock --user svc_ansible` on the target lists no recent
failures, and **Baseline preview** passes for the host.

**Undo or next:** [troubleshooting](11-troubleshooting.md#errors-after-security-hardening)
covers the other errors a hardened target can show. On Azure, run the reset
through Run Command, as [the Azure page](platform-azure.md) shows.
