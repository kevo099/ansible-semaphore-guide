# Validation record: the controller on a STIG-hardened RHEL, November 2026

[Back to validation and limits](../VALIDATION.md) · [Chapter 9](../09-security-benchmarks.md#harden-the-controller-itself)

On 13 November 2026 the guide's controller was run on RHEL 9.8 hardened with
the vendor's `stig` profile, in both orders: installed first and hardened
afterwards, and installed on a machine that was hardened first. The first
order worked for Semaphore's jobs and broke the administrator's own work with
Git and the update tool. The second order failed halfway through the
installer as it was. An independent review of the changes followed, and a
fifth round ran its fixes on a machine hardened again. This record says what
ran, what broke, what was changed and what remains unverified.

## Where

Two virtual machines on Proxmox VE, each returned to its snapshot afterwards.

| Machine | Software |
| --- | --- |
| `rhel9-vendor01`, RHEL 9.8, registered. The controller and one of its targets. | `scap-security-guide-0.1.82-2.el9_8`, `fapolicyd-2.0.1-1.el9`, Git 2.52.0, ansible-core 2.21.4, Semaphore 2.19.12 |
| `ubuntu24-vendor01`, Ubuntu 24.04.5 with Ubuntu Pro. A target, not hardened in this run. | |

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

## Offline checks

`python3 scripts/validate.py` and the 473 offline tests pass. The tests added
here cover the installer's check with no rules, with the rules in place and
in other spacing, with each rule missing, with a rule that only resembles one
of the four, with each rule after the rule that denies it, with a list that
cannot be read, with rules that are not loaded yet, with a folder that has a
space in its path, with a guide's folder behind a link, with another lab
folder, without `fapolicyd`, with an idle or permissive one and with the
option; its place before the first package in both installers; `git init`
without templates; the update tool's read as the folder's owner and its
message; the `ansible.cfg` setting; and the drop-in's mode on all four paths.

## Not established

- **An Ubuntu controller hardened with `usg`.** Not run. Ubuntu has no
  `fapolicyd` by default; what its STIG profile changes for the controller is
  unknown.
- **AlmaLinux and Rocky Linux controllers.** Not run.
- **The `0600` drop-in on the bootstrap playbook's and the cloud-init file's
  path.** It ran through `onboard-linux.sh` only.
- **The review's fixes with a second target.** Round 5 had the controller as
  its only target, and `allow_filesystem_mark` at 0.
- **A folder with a space in its path, a home folder that is itself a link,
  and rules in another order.** They ran in the offline tests, on the rule
  list of round 5. On the machine, a link to the guide's folder was tried.
- **A controller with Git before 2.46.** The update tool's read does not use
  Git; the machine had Git 2.52.0.
- **A project that Semaphore clones from a Git server,** with
  `allow_filesystem_mark = 1`. Its copy is under `/var/lib/semaphore/tmp/`,
  which the four rules do not name.
- **`--fapolicyd-ready` with trust entries on a new machine.** The option ran
  in the offline tests only; trust entries cannot be written before the files
  exist.
- **`update-runtime.sh --apply` with a real change** on a hardened controller.
- **STIG apply against a controller that is already hardened,** and this
  release's guard on such a machine.
- **FIPS mode.** The machines had the `FIPS:STIG` crypto policy and
  `crypto.fips_enabled` at 0; the audit's FIPS rule failed throughout.
- **`expose-semaphore.sh`, the browser and the CLI lessons** on a hardened
  controller. Semaphore was driven through its API.
- **A default ACL on Ubuntu,** and what Git or an editor do with it over time.
