# Validation record: a STIG-hardened controller, RHEL 9.8 and Ubuntu 24.04, November 2026

[Back to validation and limits](../VALIDATION.md) · [Chapter 9](../09-security-benchmarks.md#harden-the-controller-itself)

On 13 November 2026 the guide's controller was run on RHEL 9.8 hardened with
the vendor's `stig` profile, in both orders: installed first and hardened
afterwards, and installed on a machine that was hardened first. The first
order worked for Semaphore's jobs and broke the administrator's own work with
Git and the update tool. The second order failed halfway through the
installer as it was. An independent review of the changes followed, and a
fifth round ran its fixes on a machine hardened again. Two more rounds added
FIPS mode and a browser, and an Ubuntu 24.04 controller was hardened with
`usg` in both orders. This record says what ran, what broke, what was changed
and what remains unverified.

## Where

Two virtual machines on Proxmox VE, each returned to its snapshot afterwards.

| Machine | Software |
| --- | --- |
| `rhel9-vendor01`, RHEL 9.8, registered. The controller and one of its targets. | `scap-security-guide-0.1.82-2.el9_8`, `fapolicyd-2.0.1-1.el9`, Git 2.52.0, ansible-core 2.21.4, Semaphore 2.19.12 |
| `ubuntu24-vendor01`, Ubuntu 24.04.5 with Ubuntu Pro. A target in rounds 1 and 4, not hardened there; a controller of its own [further down](#an-ubuntu-controller-hardened-with-usg). | USG 24.04.8, needrestart 3.6 |

After the vendor's fixes and a restart, the controller had `fapolicyd` active
with `permissive = 0` and `allow_filesystem_mark = 0`, SELinux enforcing, the
`FIPS:STIG` crypto policy, `umask 077` for root and for the administrator,
`TMOUT=600`, and `Defaults timestamp_timeout=0` for sudo.

## Round 1: installed first, hardened afterwards, then updated

The published `v1.10.0` was installed with `controller/install-controller-el9.sh`,
both machines were added with `controller/onboard-target.sh`, and
**RHEL 9 · STIG apply (approval required)** ran against the controller itself.
`v1.10.0` has no guard for its own controller, so the template without a
reboot was used and the machine was restarted from its terminal.

| Step on the hardened controller | Result |
| --- | --- |
| Semaphore, PostgreSQL, **Ping**, `check-controller.py` | Passed. |
| `git checkout` of the newer release in the guide's folder | Refused: `Your local changes to the following files would be overwritten`. `git status` listed ten files as modified: seven of `controller/`, two of `scripts/` and one of `docs/`, a Markdown file that `fapolicyd` takes for Python. |
| `sudo bash controller/update-controller.sh` | Exit status 1: `Problem: uncommitted change to a guide file:  M scripts/summarize_xccdf.py`. Nothing in that file had changed. |
| `python3 /opt/ansible-lab/scripts/summarize_xccdf.py`, `/opt/ansible-venv/bin/ansible --version`, `head controller/lab-sudo.py`, as the administrator | `Operation not permitted`. With `sudo`, the guide's Python tools ran. |
| A playbook created in the lab folder, and a template for it | The file was `-rw-------`; the task failed with `[Errno 13] Permission denied`. |

**The cause** is rule 11 of the hardened rule set,
`deny_audit perm=any all : ftype=%languages`: any account but root is denied a
script that no package installed. Git cannot read such a file and reports it
as modified. The audit log held no `FANOTIFY` record of these denials, so an
empty audit log does not show that nothing was denied.

**Why jobs kept running.** The Semaphore service runs in its own mount
namespace, which this `fapolicyd` does not watch while
`allow_filesystem_mark = 0`.

With the entries below, on the same machine:

| Step | Result |
| --- | --- |
| A rule file with the two folder lines, and trust entries for `/opt/ansible-venv/` and `/usr/local/bin/semaphore` (`fapolicyd-cli --file add`, a trust file of 3,394 lines, then `fapolicyd-cli --update`) | `git status` clean in both folders; the script, the Ansible command and `head` worked as the administrator. |
| `git checkout` of this branch, `update-controller.sh`, then `--apply` | Five files updated, committed, `The readiness check passed`. The tool wrote its files `-rw-r-----` under `umask 077`. |
| `update-runtime.sh` | `Nothing to do`: the runtime was at its pinned versions. |
| `chmod 0640` on the playbook; then `setfacl -R -d -m g::rX /opt/ansible-lab` and a new file and folder | The template passed. The new file was `-rw-r-----` with the umask still 077. |
| `remove-target.sh --name`, `onboard-target.sh` for the Ubuntu machine, `lab-sudo.py`, `check-controller.py` | Passed; 15 checks true. |
| **Ping**, **Baseline preview**, **Health report**, **RHEL 9 · STIG audit**, **Ubuntu 24.04 · STIG audit** | Passed. The RHEL audit: 13 failing rules, CAT I 3, CAT II 9, CAT III 1. |

**With `allow_filesystem_mark = 1`,** so that `fapolicyd` watches the service
as well:

| State | Result |
| --- | --- |
| Without the trust entries | Semaphore did not start: `Failed to execute /usr/local/bin/semaphore: Operation not permitted`, status 203/EXEC. |
| With the trust entries | Semaphore started and **Ping** passed. **RHEL 9 · STIG audit** failed at its first task on the controller: `Failed to transfer file to '/var/lib/semaphore/.ansible/tmp/.../AnsiballZ_stat.py': [Errno 1] Operation not permitted`. |
| With `[connection]` `pipelining = True` added to the lab folder's `ansible.cfg` | Both STIG audits, **Baseline preview**, **Health report**, **Patch preview** and the administrator's own template passed. |

## Round 2: hardened first, then installed, as the installer was

The vendor's fixes were applied by hand with
`oscap xccdf eval --remediate --profile xccdf_org.ssgproject.content_profile_stig`,
which fixed 252 rules, and the machine was restarted.

| Step | Result |
| --- | --- |
| `git clone` of the guide, as the administrator | Failed: `cannot copy '/usr/share/git-core/templates/hooks/fsmonitor-watchman.sample' ... Operation not permitted`. The sample is a Perl script of the `git-core` package that is not in `fapolicyd`'s trust database. |
| `git clone --template=` | Worked. A following `git checkout` of another branch was refused as in round 1. |
| `sudo bash controller/install-controller-el9.sh --apply` | Installed the packages, the runtime, the configuration and the database, then stopped: `runuser: failed to execute /usr/local/bin/semaphore: Operation not permitted`. Exit status 1. |
| The installer again, after adding the entries of round 1 | Refused: `Existing state: /etc/semaphore. This installer runs only on a fresh VM`. |

## What was changed

- **Both installers check for an active `fapolicyd` before they change
  anything.** Without the four rules they stop and print them with the lab
  folder and the guide's folder of that run. `--fapolicyd-ready` skips the
  check for a site that allowed the same paths another way.
- **The installer makes the lab folder a repository without Git's hook
  samples,** `git init --template=`, for the reason `git clone` failed.
- **`update-controller.sh` names the cause** when Git is not allowed to read a
  file, in place of calling it an uncommitted change.
- **`ansible.cfg` sets `pipelining = True` for every connection,** so a task
  that runs on the controller writes no module file.
- **The SSH drop-in for `svc_ansible` is created `0600`** by
  `onboard-linux.sh`, the bootstrap playbook, the cloud-init file and the
  manual steps. At `0644` it failed `RHEL-09-255115` on every machine
  onboarded after its hardening.
- **Chapter 9 gained "Harden the controller itself",** with the four rules as
  one file, `35-ansible-semaphore-guide.rules`.

## Rounds 3 and 4: hardened first, then installed, with the changes

Round 3 found two faults in the first version of the changes: the new check
ended the installer with status 1 and no message when a rule was missing, and
the installer stopped late, at its own `git init`. Round 4 ran the corrected
installer on a machine hardened again from its snapshot.

| Step in round 4 | Result |
| --- | --- |
| `git clone --template=`, then `sudo bash controller/install-controller-el9.sh --apply` | Stopped with the message and the four rules, with `/opt/ansible-lab/` and the guide's folder of the run. Exit status 1; no package installed, no file created. |
| The four rules installed as `35-ansible-semaphore-guide.rules` with `sudo install ... /dev/stdin`, then `sudo fagenrules --load` | Loaded as rules 6 to 9, before the rules for shared libraries. `git status` was clean five seconds later; one second after loading, in round 3, it was not yet. |
| The installer again | `Controller installed and seeded`. |
| `onboard-target.sh` for both machines, `lab-sudo.py`, `check-controller.py` | Passed; 15 checks true. |
| `/opt/ansible-venv/bin/ansible --version` and `python3 /opt/ansible-lab/scripts/summarize_xccdf.py`, as the administrator | Worked. |
| **Ping**, **Baseline preview**, **Health report**, **Patch preview**, **RHEL 9 · STIG audit** | Passed. The audit: 15 failing rules, CAT I 3, CAT II 11, CAT III 1. |
| `update-controller.sh` and `update-runtime.sh` | Plans without a problem; nothing to update. |
| `allow_filesystem_mark = 1` with the four rules and no trust entries | Semaphore started; **Ping**, **Baseline preview**, **Health report** and both STIG audits passed. |
| `onboard-target.sh` again with the `0600` drop-in | `-rw-------` on RHEL 9.8 and Ubuntu 24.04, `sshd -t` passed on both, **Ping** passed, and the RHEL audit's CAT II fell from 11 to 10. |

The two CAT II rules that a controller installed after its hardening failed
beyond round 1's nine were `RHEL-09-255115`, the drop-in above, and
`RHEL-09-411035`: PostgreSQL's package gives the `postgres` account a login
shell. In the [morning's run](2026-11-stig-content.md), where the fixes
followed the installation, that rule did not fail and the controller ran.

## Review and round 5

An independent review of the changes found no fault that blocked their use and
seven smaller ones. What was changed for them:

- **The installer's check compares whole rules, and the place of all four.**
  It took a rule for present where a longer one contained its text, and it
  compared only the runtime's line with the shared-library rule. Now each of
  the four has to be in the list exactly, before the first of `fapolicyd`'s
  own rules that denies a shared library, a script or everything.
- **It asks the running `fapolicyd` as well.** `fapolicyd-cli --list` prints
  the compiled file, so rules written with `fagenrules` and not loaded passed
  the check, and the installation would have stopped halfway. The installer
  now reads one of the guide's scripts as the editor and stops with a message
  of its own while that is refused.
- **The guide's folder is named by the path its links lead to,** in the
  installer's message and in chapter 9, because `fapolicyd` compares resolved
  paths. A lab folder or guide's folder with a space in its path is refused
  with a message of its own: a rule written this way cannot name it.
- **The update tool no longer asks Git why a file is unreadable.** Its message
  depended on `git diff --quiet` opening the file, which Git does only from
  2.46 on, and on English error text. It now opens the file as the lab
  folder's owner and tests for `EPERM`.
- **The docs name `--fapolicyd-ready`,** `git init --template=`, reading the
  helpers with `sudo less` before the rules exist, the limit of the four rules
  to this guide's project, and what `pipelining` leaves out.

Round 5 ran on `rhel9-vendor01`, hardened again from its snapshot with
`oscap --remediate` (252 rules fixed) and restarted, as the controller and its
own target. `allow_filesystem_mark` stayed at 0.

| Step in round 5 | Result |
| --- | --- |
| `head -1 controller/lab-sudo.py` as the administrator, then with `sudo` | `Operation not permitted`; with `sudo`, the file's first line. |
| The installer without the rules, from the guide's folder and through a symbolic link to it | Stopped both times with the four rules, the guide's folder under its real path. Exit status 1; no package installed, no file created. |
| Chapter 9's block as printed, with `guide=$(realpath ~/ansible-semaphore-guide)`, then `sudo fagenrules` without `--load` | The file held the four lines with the folder's real path, `root fapolicyd 644`. `fapolicyd-cli --list` showed them, and `head` on a guide script was still refused. |
| The installer in that state | Stopped: `The four fapolicyd rules are written, but the running fapolicyd does not apply them yet`. Exit status 1; nothing installed. |
| `sudo fagenrules --load`, five seconds, the installer again | `fagenrules` reported `No change` and loaded the rules all the same; `git status` was clean; `Controller installed and seeded`. |
| `onboard-target.sh` for the controller itself, `lab-sudo.py`, `check-controller.py` | Passed; 15 checks true. |
| `update-controller.sh` with the rules | A plan without a problem; 26 files current. |
| The rule file moved away, `fagenrules --load`, `update-controller.sh` | `head` on the lab folder's script was refused, while `git status` stayed clean and the plan had no problem: Git opens a file only when the times it recorded no longer match. |
| The same after `sudo touch` on the lab folder's script | `git status` listed ` M scripts/summarize_xccdf.py`. The update tool: `Problem: Git is not allowed to read scripts/summarize_xccdf.py in the lab folder (Operation not permitted)`, with the pointer to chapter 9; exit status 1. |
| The rule file back, `fagenrules --load` | `git status` clean in both folders; a plan without a problem. |
| **Ping**, **Baseline preview**, **Health report**, **RHEL 9 · STIG audit** | Passed. The audit: 14 failing rules, CAT I 3, CAT II 10, CAT III 1. |

The list that `fapolicyd-cli --list` printed in this round, 19 rules with the
four of this guide as rules 6 to 9, is what the offline tests of the
installer's check now start from.

## Rounds 6 and 7: the browser and FIPS mode

The browser was a headless Chromium, driven by Playwright 1.63.0 from a
workstation on the lab's network. One walk has 16 steps: open the address,
sign in as the administrator, find the eight tabs, switch to **Operations**,
open **Lessons**, start a template from its form, wait for `success`, read the
log on the page and count the WebSocket frames that arrived while it ran, open
the history, inventory, Key Store, variable groups and repositories pages, and
sign out. Over HTTPS it accepted the installer's self-signed certificate
without trusting it. A walk passes when every step does and the page reported
no error, no failed request and no answer of 400 or more beyond the `401` that
asks who is signed in.

Round 6 followed the first order: installed with `--expose https`, hardened
with `oscap --remediate` (253 rules fixed), restarted, the four rules added,
then FIPS mode.

| State of the controller | Result |
| --- | --- |
| Hardened, restarted | Semaphore, nginx, PostgreSQL, `firewalld` and `fapolicyd` active; the `public` zone still listed `https`; `check-controller.py` 17 checks true. The walk passed by address over HTTPS and through the tunnel of Stage 1, 16 of 16 each. The proxy refused TLS 1.1 and answered TLS 1.2 with `ECDHE-RSA-AES256-GCM-SHA384` and TLS 1.3 with `TLS_AES_256_GCM_SHA384`. |
| `sudo fips-mode-setup --enable`, restarted | `FIPS mode is enabled.`; every service active and no failed unit; 17 checks true. Both walks passed, 16 of 16. **Baseline preview** and **Patch preview** passed. The audit: 12 failing rules, CAT I 2 (`RHEL-09-212010`, `RHEL-09-212020`: the boot loader's password and administrator name), CAT II 9, CAT III 1. |
| `remove-target.sh`, then `onboard-target.sh` as it was, in FIPS mode | The onboarding failed where it lists the machine's host keys: `sshkey_read: Ed25519 keys are not allowed in FIPS mode`, then `RESULT: FAILED: unexpected error at line 540`. |
| The same with the change below | Passed. It listed the ECDSA and RSA keys and `left out: /etc/ssh/ssh_host_ed25519_key.pub, which ssh-keygen cannot read on this system`. `lab-sudo.py`, 17 checks true, the update tools' plans without a problem, **Ping** and **Baseline preview** followed. |
| **RHEL 9 · STIG apply (approval required)**, the controller in **Limit**, already hardened and in FIPS mode | `success`; 12 failing rules before, 10 after; no reboot. **Ping** passed afterwards. |

Round 7 took the second order with FIPS mode: `oscap --remediate` (252 rules
fixed), `fips-mode-setup --enable`, one restart, and only then the guide.

| Step in round 7 | Result |
| --- | --- |
| `git clone --template=` over HTTPS, the installer with `--expose https` | Stopped with the four rules; nothing changed. |
| Chapter 9's block, `fagenrules --load`, the installer again | `Controller installed and seeded`, with the proxy's checks true. |
| `onboard-target.sh`, `lab-sudo.py`, `check-controller.py` | Passed; 17 checks true. |
| The walk by address over HTTPS (**Ping**) and through the tunnel (**Baseline preview**) | Passed, 16 of 16 each. |
| **Health report**, **Patch preview**, **RHEL 9 · STIG audit** | Passed. The audit: 13 failing rules, CAT I 2, CAT II 10, CAT III 1. |

**Changed:** `onboard-linux.sh` lists the host keys `ssh-keygen` can read and
names one it cannot, where it stopped before.

## An Ubuntu controller hardened with usg

`ubuntu24-vendor01` was the controller and its own target, installed with
`--expose https`. Before the fixes the walk passed over HTTPS and the audit
counted 64 failing rules (CAT I 4, CAT II 54, CAT III 6).

| Step | Result |
| --- | --- |
| **Ubuntu 24.04 · STIG apply (approval required)**, the controller in **Limit**, as the playbook was | The task ended without a result after three and a half minutes. `apt-get install -y audispd-plugins` had upgraded `libaudit1`; `needrestart` restarted PostgreSQL and `semaphore.service` at once, and no `usg` process was left. |
| The same with `NEEDRESTART_SUSPEND=1` for the controller | No restart of Semaphore, and the fixes ran to their end. The next task was `UNREACHABLE`: `Can't open user config file /etc/ssh/ssh_config.d/00-cipher-list.conf: Permission denied`. That file and `00-mac-list.conf` were `-rw-------`: `usg` sets `umask 0077`, and its fix writes them with `echo >>`. `ssh -G` ended the same way for `semaphore` and for the administrator. |
| `chmod 0644` on the two files, restarted | Services active, except `sssd.service`, which the fixes install without a configuration. An interactive login asked `Do you agree? [y/N]`. `git status` clean in both folders, the Ansible command and the summary script worked, 17 checks true, the update tools' plans without a problem, `remove-target.sh`, `onboard-target.sh` and `lab-sudo.py` passed. The walk passed by address over HTTPS and through the tunnel, 16 of 16 each. The audit: 10 failing rules, CAT I 2 (`UBTU-24-102000`, the boot loader's password, and `UBTU-24-600030`, FIPS mode), CAT II 8. An Ubuntu target counted 10 in the [morning's run](2026-11-stig-content.md) as well, so the readable files add no finding. |
| **Patch, no reboot**, the hardened controller in **Limit** | `success` after eleven minutes, without a restart of Semaphore. The report: `updates completed. Reboot required; left for the operator.`, then the sentence about `sudo needrestart`; `needrestart -b` listed 20 services that waited. |
| A new installation, then **STIG apply** with the playbook as it is now | `success`: 64 failing rules before, 11 after; no restart of Semaphore during the run; both files `-rw-r--r--`; the last message says that they were made readable. After a restart the walk passed over HTTPS and the audit counted 10. |
| Hardened first with `sudo usg fix disa_stig` in a terminal, restarted, then the guide | The two files were `-rw-------` here as well. A plain `git clone` and the installer worked; `onboard-target.sh` ended with the same `Can't open user config file` message. After the `chmod` it passed, and so did both walks, 16 of 16; the audit counted 10. |
| The same order with the installer as it is now | Stopped at once: `The ssh command does not start for an ordinary account on this machine`, with ssh's message and the `chmod` command. Exit status 1; no package installed, no file created. After that command it installed; the onboarding, 18 checks true, **Ping** and **Baseline preview** followed. |

On RHEL 9.8 without hardening the same installer passed that check and
installed; `service_can_start_ssh` was true among its 16 checks.

**Changed:**

- **STIG apply and Patch suspend `needrestart`** where the target is the
  controller the run comes from, which both now recognize before the first
  package changes. The patch report asks for `sudo needrestart` or a reboot.
- **On its own controller the Ubuntu STIG apply gives the SSH client's files
  mode `0644` back,** in the same command as the fixes, because no later task
  could connect. Its last message says so; for another target it names the
  files and the command.
- **The readiness check has `service_can_start_ssh`,** and both installers
  check that `ssh` starts for an ordinary account before they change anything.

## Offline checks

`python3 scripts/validate.py` and the 483 offline tests pass. The tests added
here cover the installer's check with no rules, with the rules in place and
in other spacing, with each rule missing, with a rule that only resembles one
of the four, with each rule after the rule that denies it, with a list that
cannot be read, with rules that are not loaded yet, with a folder that has a
space in its path, with a guide's folder behind a link, with another lab
folder, without `fapolicyd`, with an idle or permissive one and with the
option; its place before the first package in both installers; `git init`
without templates; the update tool's read as the folder's owner and its
message; the `ansible.cfg` setting; the drop-in's mode on all four paths; a
host key that `ssh-keygen` refuses; `needrestart` suspended for the
controller only, in both playbooks, and the controller recognized before the
first package changes; the Ubuntu fix's command on its own controller, run
with a stand-in for `usg`; both playbooks' last messages; the installers'
check that `ssh` starts; and the readiness check's `service_can_start_ssh`.

## Not established

- **AlmaLinux and Rocky Linux controllers.** Not run. Their vendors' profiles
  are the RHEL 9 STIG with `fapolicyd`, so the four rules should apply; that
  is an expectation, not a result.
- **Two machines at once.** After round 4 every controller had itself as its
  only target: the lab's capacity check refused a second guest that day.
- **FIPS mode chosen when the system is installed, and FIPS on Ubuntu,** which
  needs Ubuntu Pro's FIPS packages. RHEL's ran with `fips-mode-setup --enable`
  on an installed system.
- **`expose-semaphore.sh` run later on a hardened controller,
  `--expose http`, a browser other than Chromium, and the CLI lessons.** The
  installer's `--expose https` and the tunnel ran.
- **A tailoring file with an Ubuntu controller's own apply, and Patch with an
  approved reboot there.** The apply ran with the profile's name, the patch
  without a reboot.
- **A later `usg`.** The two files of the SSH client were left for root only
  by USG 24.04.8.
- **The `0600` drop-in on the bootstrap playbook's and the cloud-init file's
  path.** It ran through `onboard-linux.sh` only.
- **A folder with a space in its path, a home folder that is itself a link,
  and rules in another order.** They ran in the offline tests, on the rule
  list of round 5. On the machine, a link to the guide's folder was tried.
- **A controller with Git before 2.46.** The update tool's read does not use
  Git; the machine that showed its message had Git 2.52.0.
- **A project that Semaphore clones from a Git server,** with
  `allow_filesystem_mark = 1`. Its copy is under `/var/lib/semaphore/tmp/`,
  which the four rules do not name. Rounds 5 to 7 left that setting at 0.
- **`--fapolicyd-ready` with trust entries on a new machine.** The option ran
  in the offline tests only; trust entries cannot be written before the files
  exist.
- **`update-runtime.sh --apply` with a real change** on a hardened controller.
- **A default ACL on Ubuntu,** and what Git or an editor do with it over time.
