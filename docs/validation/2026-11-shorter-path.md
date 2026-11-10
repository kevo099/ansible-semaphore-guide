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
| Stage 4 | Removing the account by hand on a retired machine | On Ubuntu 24.04 the page's lines removed the account, its home, the sudo rule and the SSH drop-in; `visudo -c` and `sshd -t` passed. On AlmaLinux 9.8 the same lines without the first one had already done so. |

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

## Not established by this run

- **A RHEL controller, Baseline on RHEL, and the opt-in password on RHEL.**
  The RHEL guest's registration was still removed on the vendor's side, as in
  the earlier record, so it served only as a machine that already existed:
  onboarded with the one command, Ping and the Health report.
- **Azure** was not rerun. The cloud-init file's default, without a password,
  is what the Azure page uses, and Run Command still gives the script its
  inputs as environment variables; offline tests cover both.
- **The one command** against an administrator who logs in over SSH with a
  password, a DNS name or an IPv6 address in place of an IPv4 address, a
  machine already hardened with the vendor STIG, and a run without a terminal.
  Offline tests, with stand-ins for SSH, cover the option handling, the
  refusals, the hand-off to `add-target.sh`, and that the command sent to the
  machine removes its temporary folder; no run looked for a leftover folder.
- **Reboot one target** on Enterprise Linux, and its refusal of a group in
  **Limit**, which offline tests cover.
- **The Health report's other reasons** for `needs attention`: a full root
  file system or memory, failed units, a pending reboot and an unsynchronized
  clock were not provoked on a live host.
- **The by-hand account removal's first line**, `loginctl terminate-user`, on
  Enterprise Linux.
- **A browser walk through Semaphore's forms**, including the reboot
  template's prompt as the UI draws it; the task ran with the value the prompt
  sends.
