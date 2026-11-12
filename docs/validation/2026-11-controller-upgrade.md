# Validation record: upgrading an old controller on RHEL, November 2026

[Back to validation and limits](../VALIDATION.md) · [Update a controller](../controller-update.md)

On 12 November 2026 a RHEL 9.8 controller was installed from `v1.1.0`, the
oldest release with an Enterprise Linux installer, used the way that release
described, and then brought to this release without being rebuilt. The run
answers what an existing controller needs, and it is the first time the update
tool ran on RHEL and the first time a RHEL controller managed a second machine.

## How it ran

- **Guests:** two registered vendor guests on Proxmox VE 9.2, rolled back
  afterwards: RHEL 9.8 as the controller and as one target, and Ubuntu 24.04.5
  attached to Ubuntu Pro as the other target. Each administrator needed a
  password for `sudo` and logged in over SSH with a key.
- **The old controller:** `sudo bash scripts/install-controller-el9.sh --apply`
  from tag `v1.1.0` gave Semaphore 2.19.12, ansible-core 2.20.8 and eleven
  templates without tabs. RHEL's own `ansible-core` 2.14.18 package was on the
  machine before, and was the same afterwards.
- **Used as `v1.1.0` described:** the service key appended by hand to
  `svc_ansible`'s authorized keys on both machines, `scripts/add-target.sh`
  with the names `lab-ubuntu` and `lab-rhel`, a **Lab sudo** key made in the
  Key Store and chosen as the inventory's Sudo Credentials, **Ping** and
  **Baseline apply**, and the administrator's password changed, so that the
  installer's password no longer logged in. The first round also had a playbook
  of the operator's own, committed in the lab folder, with a template for it.
- **Two rounds.** The first used the published `v1.10.0` to find what was rough.
  Both guests were then rolled back, the old controller was built again, and
  the second round used this release's files.
- **Semaphore** was driven through its API over the SSH tunnel of Stage 1, with
  the request bodies the UI sends; the UI was not clicked through. The commands
  on the controller were typed in a terminal session, prompts included.

## What passed

| Step | Result |
| --- | --- |
| The plan, `sudo bash controller/update-controller.sh` | Asked for a Semaphore login, because the installer's password no longer worked. Listed 11 files to add and 8 to update, the five `content/` folders, 2 variable groups, 7 tabs, 16 templates to add, 8 templates to put on their tab and 3 replaced STIG templates. The readiness check passed before the update. |
| `--apply`, first round | `Committed 20 file(s)`, `Updated to v1.10.0. The readiness check passed.` The new files had the group `semaphore` and the SELinux type `usr_t`. A second plan listed nothing to add. The operator's own playbook and template were kept, and the template ran. |
| Jobs with ansible-core 2.20.8 still installed | **Ping**, **Baseline preview**, **Health report**, **Patch preview** and the operator's own template succeeded on both machines. |
| `--apply --remove-replaced`, as one command in the second round | Updated the files, added the tabs and templates, saved the old templates and removed the three replaced ones. The project then had 24 templates on seven tabs, as a fresh installation has. |
| The plan's last lines, second round | `Ansible runtime /opt/ansible-venv: 2.20.8 installed, 2.21.4 pinned` and `SSH connection reuse for Semaphore jobs: not set`, after the plan and after the update, with the plan saved to a file. |
| `sudo bash controller/update-runtime.sh`, then `--apply` | The plan listed four packages and the SSH setting. `--apply` ended with `Updated. The readiness check passed.`; Semaphore was down for 2.5 seconds. A second run reported `Nothing to do`, and the update tool's plan no longer named either. |
| Going back with the saved files | The four commands of [the update page](../controller-update.md#do-update-the-ansible-runtime-and-semaphores-ssh-settings) restored ansible-core 2.20.8 and the earlier configuration; `--apply` then updated both again. |
| `bash controller/onboard-target.sh ADMIN@UBUNTU ADMIN@RHEL --keep-password` | On each machine: authorized keys replaced by the service key, the sudo rule and the SSH drop-in written, the password kept, `RESULT: OK`. Then `Already present as lab-ubuntu` and `Already present as lab-rhel`, and `Prepared and in the inventory:` with both. |
| `sudo python3.12 controller/lab-sudo.py` | Found the **Lab sudo** key that had been made by hand in the UI: `already uses the key 'Lab sudo' ... nothing changed`. |
| Jobs with ansible-core 2.21.4 | **Ping**, **Baseline preview** with `changed=0`, **Health report** and **Patch preview** succeeded on both machines. **Reboot one target** restarted the Ubuntu machine from the RHEL controller and found a new boot ID. |
| **Patch, allow required reboot** on both machines | Updated the Ubuntu machine, which asked for no reboot, then the RHEL machine, which went from 9.8 to 9.9 and, being the controller itself, restarted in the middle of its own task; see below. Afterwards the readiness check passed on RHEL 9.9, no unit had failed, and the **Health report** read both machines, with `Pending package updates: none` for Ubuntu. |
| The same template with the corrected playbook | The update tool delivered the one changed file, `playbooks/patch.yml`. With the controller made to need a reboot again, the task succeeded with `lab-rhel: updates completed. Reboot required and left alone: lab-rhel is the controller this run comes from ...`, and the controller's boot time was unchanged. |
| The controller throughout | SELinux enforcing with no denial, no failed unit, and the readiness check passing after every step. |

## What the runs changed

- **A machine listed under an earlier name.** With `v1.10.0`, the one command
  prepared such a machine and then ended with `Not finished` and exit status 1,
  because `add-target.sh` refused an address that the inventory listed under
  another name. When the name comes from the machine, the group is the same,
  the line is the plain one the script writes and the machine presents the key
  that is already trusted, `add-target.sh --from-info` now says `Already
  present as NAME` and changes nothing. A name given with `--name` is refused
  as before.
- **The runtime and the SSH setting.** The update tool said nothing about
  ansible-core 2.20.8, and the SSH connection reuse was a `sed` command on the
  update page. [`controller/update-runtime.sh`](../../controller/update-runtime.sh)
  now shows and applies both, and the update tool names them when they are
  older.
- **The login question.** It was written to standard output, so a plan saved
  with `> plan.txt` waited for an answer to a question nobody saw. It is now
  written to standard error.
- **A patch run that reaches the controller.** In this lab the controller was
  also one of its own targets. **Patch, allow required reboot** patches the
  whole lab group, so it updated the controller and then restarted it: the
  task ended there, Semaphore kept showing it as running after the restart,
  and any host after the controller would have stayed unpatched.
  `playbooks/patch.yml` now recognizes the controller the run comes from by
  its boot ID, as the reboot template does, patches it, and leaves its reboot
  for its own terminal with a line that says so.
- **A fault in the new script, found by this run.** Its first build set
  `LC_ALL=C`, as the scripts that read a machine's output do. Ansible refuses to
  start without a UTF-8 locale, so the readiness check at the end reported
  `ansible_is_available` as failed although the update had worked. The script
  no longer sets it, a failing readiness check now names its checks, and an
  offline test covers both.

## Not established by this run

- **A RHEL controller from a release between `v1.2.0` and `v1.9.0`.**
  Controllers from `v1.4.0`, `v1.8.0` and `v1.9.0` were updated in
  [September](2026-09-update.md) and in the two earlier November records,
  [the five stages](2026-11-workflow-proxmox.md) and
  [the shorter path](2026-11-shorter-path.md), the last two on Ubuntu. What
  those controllers lack is part of what a `v1.1.0` controller lacks.
- **`update-runtime.sh` on Ubuntu, AlmaLinux or Rocky Linux,** with the UI
  exposed over HTTPS, and while a task runs. Its refusal while a task runs, a
  failed installation with the earlier versions installed again, packages the
  operator added and a configuration of another form are covered by offline
  tests only.
- **The update tool's refusals on RHEL:** files that both the operator and the
  release changed, staged changes and links. Offline tests and the September
  record on Ubuntu cover them.
- **RHEL releases other than 9.8 as a starting point,** and a controller whose
  targets include a machine hardened with the vendor STIG. The controller
  kept working after the patch run took it to RHEL 9.9; nothing was installed
  on 9.9.
- **The health report's update count on RHEL.** It said `not checked` for the
  RHEL machine in every run here, before and after patching, because
  `svc_ansible` could not read the system's package cache without sudo, so
  its `OK` said nothing about pending updates. **Patch preview** showed them.
