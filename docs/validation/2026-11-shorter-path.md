# Validation record: the shorter path on Proxmox, November 2026

[Back to validation and limits](../VALIDATION.md) · [The workflow](../../README.md#the-workflow)

On 10 November 2026, after [the five stages were followed on Proxmox](2026-11-workflow-proxmox.md),
the path was shortened: one command on the controller that onboards machines
that exist, a helper that gives Semaphore the sudo password, a command that
retires a target, an opt-in sudo password in the cloud-init file, an
**Operations** tab with a health report and a reboot template, and
[a page of runbooks](../runbooks.md). The new files and pages were then run as
written on the same Proxmox VE 9.2 cluster, with disposable guests that were
destroyed or rolled back afterwards.

## How it ran

- **Controllers:** an Ubuntu 24.04.5 guest installed with
  `controller/install-controller.sh --apply` from this release; the same guest
  again, rolled back and installed from tag `v1.9.0`, then updated; and a
  fresh AlmaLinux 9.8 guest for `controller/install-controller-el9.sh`.
- **Targets:** one small guest rebuilt in turn from the Ubuntu 24.04,
  AlmaLinux 9.8 and Rocky Linux 9.8 cloud images of the earlier record, a
  Proxmox template made from it with a linked clone, and a RHEL 9.8 guest as a
  machine that already existed. Its administrator needed a password for
  `sudo`; the other administrators did not. Every administrator logged in
  over SSH with a key.
- **Semaphore** was driven through its API over the SSH tunnel of Stage 1,
  with the request bodies the UI sends, as in the earlier record; the UI was
  not clicked through.
- The commands on the controller were typed in a terminal session, prompts
  included; no password was passed on a command line.
- Enterprise Linux was restarted through the reboot template only in the
  regression after the review, on RHEL.

## Results

| Area | What ran | Result |
| --- | --- | --- |
| Stage 1 | `install-controller.sh --apply` on Ubuntu 24.04.5 | Readiness `"passed": true`; seven tabs and 24 templates. `~/svc_ansible.pub` was the administrator's own file, mode 0644, identical to `/etc/semaphore/svc_ansible.pub`, and the closing lines named `bash controller/onboard-target.sh ADMIN@ADDRESS`. |
| Stage 1 | `install-controller-el9.sh --apply` on fresh AlmaLinux 9.8 | Readiness `"passed": true`; the same key copy, labelled `user_home_t`, identical to the service key. |
| Stage 2 | `onboard-target.sh` with two machines in one run: RHEL 9.8 and Ubuntu 24.04.5 | One prompt for the controller's `sudo`, the shared password asked once, SSH's question with each machine's RSA fingerprint, and on RHEL the machine's own `sudo` prompt. Each machine printed `RESULT: OK` and was added under `[enterprise_linux]` or `[ubuntu]`; the run ended with `Prepared and in the inventory:` and both names, exit status 0. |
| Stage 2 | The same command again for a machine that was done | The script reported what was unchanged, `add-target.sh` said `Already present`, exit status 0. |
| Stage 2 | `--extra-key` with the administrator's own public key | The account's authorized keys were the service key and that key; the administrator then logged in as `svc_ansible` with it. |
| Stage 2 | `onboard-linux.sh --keys ... --ask-password --controller-address ...` by hand on Ubuntu 24.04.5 | Asked for the password twice, then `password: set from PASSWORD_HASH` and `RESULT: OK`; `sudo` accepted the typed password. |
| Stage 4 | `lab-sudo.py`, a second run, then `--replace` | Created the key `Lab sudo` with an empty Username and selected it for `Lab inventory file`; the second run changed nothing; `--replace` stored a new password in the same key. |
| Operations | **Health report** before Semaphore held any sudo password, on RHEL 9.8 and Ubuntu 24.04, and later on AlmaLinux 9.8 | Every run showed `changed=0` and ended with `NAME: OK` or, for example, `NAME: needs attention: 17 package update(s) pending`. The Ubuntu host reported no pending updates until Baseline apply refreshed its package lists, and 45 afterwards: the count is as fresh as the host's package data. |
| Lessons | **Ping**, **Baseline preview**, **Baseline apply** twice, on Ubuntu 24.04 | The first apply made changes and the second showed `changed=0`. A preview that also covered the RHEL host failed there at the package step, on the repository error noted below. |
| Operations | **Reboot one target** on Ubuntu 24.04 | Without the acknowledgement it stopped with `Refusing to reboot ...` and rebooted nothing. With `REBOOT NOW` the host restarted, its boot ID changed, and the run ended green. |
| Runbook | Changing the shared sudo password | The one command again with a new password, then **Baseline preview**: `Incorrect sudo password`, as the runbook warns. After `lab-sudo.py --replace` it passed. |
| Stage 4 | `remove-target.sh --name NAME` | Removed the inventory line and the trusted key, kept a backup of `lab.ini`, and left the known-hosts file with its owner and mode; readiness still passed. A second run said `nothing changed`, exit status 0; a group's name was refused. |
| Stage 3 | `fill-cloud-init.sh --with-password`, the file as `cicustom vendor=` | AlmaLinux 9.8, Rocky Linux 9.8 and Ubuntu 24.04 each printed `onboard: svc_ansible is ready, with its sudo password set` and the four lines on the serial console. Nobody logged in to the VM: `add-target.sh --from-info` with the console's lines, then **Ping** and **Baseline preview** passed, and **Baseline apply** on AlmaLinux. |
| Stage 3 | What the opt-in leaves on the VM | On all three systems the password field held a SHA-512 hash, `/run/ansible-lab-onboard.hash` was gone, and no unit had failed. On AlmaLinux 9.8, in addition: cloud-init's logs and the first boot's journal did not hold the hash; cloud-init's own copies of the file under `/var/lib/cloud/instances/` were readable by root only, modes 0600 and 0400; SELinux logged no denial; and password login over SSH was refused for `svc_ansible`. |
| Runbook | A Proxmox template from the prepared VM, and a linked clone | The clone kept `cicustom`, prepared itself at its first boot with the password set, and was added from its console lines; **Ping**, **Baseline preview** and **Health report** passed. |
| Update | A controller installed from `v1.9.0`, then `update-controller.sh` | The plan listed two guide files to add, one tab and two templates. `--apply` added them and passed readiness; a second plan had nothing to do; **Health report** then ran. |
| Runbook | The controller was rebuilt | A new controller with a new service key ran the one command with `--keep-password` for a machine the old controller had prepared; the key was replaced, the password kept, and after `lab-sudo.py` **Baseline preview** passed. |
| Stage 4 | Removing the account by hand on a retired machine | On Ubuntu 24.04, and on RHEL 9.8 while Ansible still held a session of the account, the page's lines removed the account, its home, the sudo rule and the SSH drop-in; `visudo -c` and `sshd -t` passed. On AlmaLinux 9.8 the same lines without the first one had done so. |

## After the review

Two independent reviews followed the runs above, one of the new scripts and
one of the pages against the code. Their fixes are listed in the next
section; because they touch the two scripts every target passes through, an
Ubuntu 24.04.5 controller was installed once more from the corrected files,
with the RHEL 9.8 guest as its target.

| What ran | Result |
| --- | --- |
| `onboard-target.sh` for the RHEL machine, then `remove-target.sh`, then the one command again | Added, removed and added again. `lab.ini` and its backup stayed with the lab folder's owner, its group and mode 0640, and the known-hosts file with `root:semaphore`, mode 0640; readiness passed. |
| The same removal and addition after the lab folder was given to another account, run from the administrator's home | Both worked; the inventory stayed that account's file, readable by the service, and **Ping** passed afterwards. |
| Ctrl-C at the machine's own `sudo` prompt during the one command | `sudo: a password is required`, `The script did not finish on ...`, `Not finished: ...`, exit status 1; the machine had no temporary folder and no hash file left. |
| The controller onboarded as a target of itself, then **Reboot one target** with its name in **Limit** and `REBOOT NOW`, as a run and as a Dry Run | Both stopped with `... is the controller this run comes from ... Nothing was changed.`; the controller kept its one boot. |
| **Reboot one target** for the RHEL 9.8 machine | It restarted and answered again: the boot ID changed, the system state was `running`, no unit had failed. |
| **Health report** | `NAME: OK` for RHEL; `needs attention: 101 package update(s) pending` for the Ubuntu controller. |
| `fill-cloud-init.sh --password-hash-file` over a file that existed with mode 0664 | The file had mode 0600 afterwards and held the entry; `cloud-init schema` accepted it. |

## RHEL, once it was registered again

On 11 November 2026 the RHEL 9.8 guest was registered with the vendor again,
so its package repositories answered. It then served as a controller and as
that controller's one target, from the published tag `v1.10.0`.

| What ran | Result |
| --- | --- |
| `sudo dnf install -y git`, `git clone`, `install-controller-el9.sh --plan` and then `--apply`, on RHEL 9.8 | Exit status 0 and readiness `"passed": true`; seven tabs and 24 templates; PostgreSQL 16 from the AppStream module and Python 3.12; SELinux stayed enforcing and logged no denial. `~/svc_ansible.pub` was identical to the service key, labelled `user_home_t`. |
| `fill-cloud-init.sh --with-password` on that controller | Asked for the password twice and printed its warning; the file had mode 0600. |
| The filled file as vendor data at a first boot of cloud-init 24.4 on RHEL 9.8 | `onboard: svc_ansible is ready, with its sudo password set` and the four lines. cloud-init created the account; its password field held a SHA-512 hash and its sudo rule was `svc_ansible ALL=(ALL:ALL) ALL`. `/run/ansible-lab-onboard.hash` was gone, cloud-init's logs and the boot's journal did not hold the hash, cloud-init's copies of the file were readable by root only, no unit had failed and SELinux logged no denial. |
| `add-target.sh --from-info` with those lines, `lab-sudo.py`, then **Ping**, **Baseline preview**, **Baseline apply** twice and **Health report** | All passed. The first apply showed `changed=1` and the second `changed=0`; the report ended with `needs attention: 180 package update(s) pending`. |
| `onboard-target.sh --keep-password` from the RHEL controller, for the machine cloud-init had prepared | `RESULT: OK`, `Already present`, exit status 0. |
| `remove-target.sh --name NAME` with SELinux enforcing, a second run, and a group's name | Removed the inventory line and the trusted key. `lab.ini` and its backup kept the lab folder's owner, its group, mode 0640 and the SELinux type `usr_t`; the known-hosts file kept `root:semaphore`, mode 0640 and `etc_t`; readiness passed and no denial was logged. The second run said `nothing changed`; the group's name was refused. |
| The one command again, then **Ping** and **Baseline preview** | `Added ...`; both passed. |

The guest was an installed RHEL, not a cloud image, so three things differ
from a reader's new VM. cloud-init was installed there from AppStream. The
seed was the folder `/var/lib/cloud/seed/nocloud` with the three files of
Stage 3 in place of an ISO, and a drop-in named NoCloud as the data source,
because cloud-init did not find the folder on its own and stayed disabled.
The user data kept the guest's host keys and name, and cloud-init's network
configuration was switched off. The guest's own earlier `svc_ansible` account
was first removed with the by-hand lines of Stage 4; on a pass before that,
with the account still there, the file set its password and printed the same
lines.

## What the runs and the review changed

- **The Health report failed at its first run.** One option of its `df`
  command contains commas, and the playbook's bracketed list split it into
  four arguments. The option is now quoted, and an offline test refuses such a
  split in any playbook.
- **The one command printed two different next steps**, its own and
  `add-target.sh`'s. It now says `Nothing to paste`, drops the second hint and
  ends with one.
- **Removing the account by hand failed on Ubuntu** with
  `userdel: user svc_ansible is currently used by process`, because the
  account's processes were still ending. The page now ends the account's
  sessions first and says to run the line again.
- **The password's length was counted in bytes** in the two shell scripts and
  in characters in the bootstrap playbook; all three now count characters.
- **The one command removed any other key** the account had, because the
  script replaces the list. `--extra-key` keeps a key of your own.
- **Root wrote in the editor's lab folder.** `add-target.sh` and
  `remove-target.sh` wrote the inventory as root, in a folder whose owner
  could swap a name for a link between two steps. Both now make every change
  there as the folder's owner; root's rights are used only for the service's
  known-hosts file. `add-target.sh` had written as root in every earlier
  release.
- **A filled cloud-init file with a hash could stay readable by others**: the
  shell keeps the mode of a file that exists, and Stage 3 first makes that file
  without a secret. `fill-cloud-init.sh` now gives an output file that holds a
  hash mode 0600 itself, and refuses a key comment outside plain ASCII, which
  could produce a file cloud-init cannot read.
- **The one command** could leave its temporary folder, with the password's
  hash, on a machine when the shell there was killed; the command it sends now
  removes the folder on every way out. It sent `scp` an IPv6 address without
  brackets, and two key files could run into one line when the first had no
  final line break.
- **Reboot one target** would have restarted the controller itself, had it
  been in its own inventory; it now refuses.
- **The pages** showed `lab-sudo.py`'s prompts in the wrong order, told the
  reader to pause schedules after changing the password instead of before, and
  showed sample output the code does not print; these and smaller points were
  corrected.
- **`cloud-init schema` stopped with `PermissionError`** for the administrator
  on the RHEL guest while cloud-init was installed there but had never run;
  with `sudo` it printed `Valid schema`, and after cloud-init's first run it
  worked without. Stage 3 now names the error and the `sudo` form.

## Not established by this run

- **Red Hat's cloud image on Proxmox, and a RHEL controller with a second
  machine.** RHEL's cloud-init ran the filled file on an installed guest from
  a seed folder, as described above, not on the vendor's KVM guest image with
  `cicustom`; and the RHEL controller managed only itself, so the reboot
  template was not run from it. `update-controller.sh` was not run on RHEL.
- **Azure** was not rerun. The cloud-init file's default, without a password,
  is what the Azure page uses, and Run Command still gives the script its
  inputs as environment variables; offline tests cover both.
- **The one command** against an administrator who logs in over SSH with a
  password, a DNS name or an IPv6 address in place of an IPv4 address, a
  machine already hardened with the vendor STIG, and a run without a terminal.
  Offline tests, with stand-ins for SSH, cover the option handling, the
  refusals and the hand-off to `add-target.sh`.
- **Reboot one target** with a group or several hosts in **Limit**, which
  offline tests cover, and on AlmaLinux and Rocky Linux.
- **The Health report's other reasons** for `needs attention`: a full root
  file system or memory, failed units, a pending reboot and an unsynchronized
  clock were not provoked on a live host.
- **A dropped connection** during the one command, and an IPv6 address:
  offline tests run the command it sends in real shells, with a signal and
  with a bracketed address for the copy.
- **One known gap, left as it is:** cloud-init writes the hash file and sets
  its root-only mode right after, so for an instant at the first boot the file
  has the default mode. The script's header says so.
- **A browser walk through Semaphore's forms**, including the reboot
  template's prompt as the UI draws it; the task ran with the value the prompt
  sends.
