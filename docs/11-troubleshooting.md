# 11. Troubleshoot by layer

[Back to the guide](../README.md) · [Learning exercises](12-learning-path.md)

Start with the first failed layer: guest state → network → SSH trust → login
key → Python → sudo → module → application. Preserve the original error and
the exact code ref, inventory and execution context. Do not repeatedly reboot
or loosen security controls without understanding what failed.

## Common symptoms

| Symptom | Check first | Appropriate next step |
| --- | --- | --- |
| `add-target.sh` refuses a newly onboarded target's lines, or the target fails Ping or its first sudo task | Which onboarding step did not finish | Follow [when a step fails](ONBOARDING.md#when-a-step-fails) on the onboarding page. |
| SSH times out | Correct guest/address, route, firewall and listening SSH service | Use the trusted console to verify networking and daemon state. |
| Host-key mismatch | Was the guest rebuilt, rolled back, or replaced at the same address? | Verify the current fingerprint through a trusted independent path before updating only its matching pin. |
| Permission denied (publickey) | Login name, selected key, authorized-key permissions and algorithm policy | Compare the intended public key to the target's authorized key; inspect the SSH debug output privately. |
| CLI works, Semaphore fails | Service-user known-hosts, agent key, inventory and sudo credential | Reproduce in the service context; do not disable host checking. |
| Ansible cannot import `apt`/`dnf` | Target `/usr/bin/python3` and OS package bindings | Install the required target package through bootstrap; verify interpreter selection. |
| Missing sudo password | Inventory's sudo credential or CLI `-K` | Supply the intended credential, and verify `sudo -v` independently. |
| Semaphore task fails with `Destination /etc not writable` or similar only when something must change | The sudo credential's Username | Leave it empty. Semaphore passes a username there as `--become-user`, so tasks become that user instead of root. |
| Semaphore cannot read a file (`Permission denied`) in a folder or bare repository it reads through the `semaphore` group | The file's group and mode, for example `find DIR ! -group semaphore` | Hand the file to the group with `sudo chgrp semaphore` and make it group-readable; do not add your account to that group or loosen the folder. |
| `requiretty` or sudo/PTY issue | Scoped sudoers settings and pipelining | Validate the intended service account's rule with `visudo`; preserve password-backed sudo. |
| No hosts matched | Working directory, inventory path, `lab` group and `--limit` | Run `ansible-inventory --graph` and `--list-hosts` before applying anything. |
| Explicit limit rejected | Missing limit or literal `all`/`*` | Name one approved target or the intended lab group. |
| Reboot option rejected | Boolean versus string | Use JSON `{"allow_reboot":true}` in extra variables. |
| Check mode skipped work | A required package, directory or group is not installed yet | Read the explanation and verify the dependent task after the first real apply. |
| Package-manager lock | Another package update is active | On Ubuntu, the lessons, the STIG scan and onboarding wait up to ten minutes for the apt lock, so a run soon after a VM's first boot can pause while its first updates finish. On Enterprise Linux, dnf waits until the other package operation finishes. A lock error after that still means: wait for the owning operation; do not delete lock files or kill it blindly. |
| `sudo` fails for `svc_ansible` on a STIG-hardened host even with the right password | `pam_faillock` locked the account after three wrong passwords within 15 minutes; the vendor STIG sets no automatic unlock | `sudo faillock --user svc_ansible` shows the failures. Reset as root, from the console or Azure Run Command, with `faillock --user svc_ansible --reset`, then correct the password Ansible or Semaphore uses. |
| Task appears finished but recap is incomplete | Output persistence and stream timing | Wait for the complete host recap, then inspect the actual failure. |
| Browser works but task is queued | Application concurrency and another running task | Check task state before launching duplicates. |
| Restored UI cannot decrypt keys | Matching database and access-key encryption configuration | Restore the matching private configuration; generating a new key will not decrypt the old records. |

## Semaphore feature symptoms

These come from the Semaphore Community 2.19.12 feature campaign; the linked
chapter explains each one.

| Symptom | Likely cause | Where to read |
| --- | --- | --- |
| A schedule ran hours early or late | Schedules use `schedule.timezone` (UTC by default), and a one-time `run_at` drops the offset you send | [Schedules](16-semaphore-operations.md#do-create-a-one-time-schedule) |
| A schedule stopped running after an API edit | A schedule `PUT` clears the fields you leave out, including **active** | [Schedule edits](16-semaphore-operations.md#concept-schedule-parameters-and-edits) |
| A task shows `stopped` but its play kept running | Stop ends the task record before every process has ended; a force-stopped queued task can still run | [Stop without trusting the badge](16-semaphore-operations.md#check-stop-without-trusting-the-badge) |
| A webhook returns 204 but no task starts | The receiver answers 204 even for a wrong secret or no match | [Prove dispatch](17-api-and-integrations.md#check-prove-dispatch-and-refusal) |
| An alert failed and the task log now shows a webhook URL | Failed deliveries are logged with their URL | [Recipients and delivery](16-semaphore-operations.md#check-recipients-and-delivery) |
| No password login works, not even the local admin | LDAP is enabled and its server is unreachable | [LDAP limitations](appendices/identity-providers.md#concept-ldap-limitations-in-21912) |
| A runner task waits forever | The only eligible runner is offline, or remote execution is on with no runner | [Runner availability](18-runners.md#check-execution-and-availability) |
| An imported project's tasks fail with `secret must be valid json in key` | Exports omit Key Store values; re-enter them privately | [Make the imported project runnable](appendices/maintenance.md#check-make-the-imported-project-runnable) |
| Tasks that use credentials fail with `illegal base64 data` after a downgrade | 2.18 cannot read credentials stored by 2.19 | [Why a downgrade is not a rollback](appendices/maintenance.md#concept-why-a-downgrade-is-not-a-rollback) |

## SSH identity selection

For your interactive controller terminal, this explicitly selects one key:

```bash
ssh -vv -i ~/.ssh/ansible_lab -o IdentitiesOnly=yes \
  svc_ansible@ubuntu.example.test
```

Keep debug output private; it can reveal usernames, addresses and paths.
Semaphore uses a per-task agent for its Key Store key. `IdentitiesOnly=yes`
without a matching `IdentityFile` can prevent that key from being offered.
The supplied service environment deliberately leaves that option out while
retaining strict host-key verification.

If the SSH client rejects permissions on a client configuration file, inspect
that file's ownership and mode. Correct the owning configuration rather than
turning off server identity checks.

## Errors after security hardening

Inspect the effective settings and audit evidence before changing policy:

```bash
sudo /usr/sbin/sshd -t
sudo /usr/sbin/sshd -T
sudo visudo -cf /etc/sudoers
systemctl --failed
sudo journalctl -u ssh --since today --no-pager
```

Use `sshd` as the journal unit on Enterprise Linux. If access is broken, perform these
checks through the guest console. Compare the result with the pre-hardening
record, including crypto policy and which host keys are currently offered.

### Application allowlisting and temporary modules

Ansible may fail when an application allowlisting policy rejects a transferred
temporary Python module. SSH pipelining can avoid that transfer-and-execute
path; the supplied `ansible.cfg` enables it. Validate sudo/TTY compatibility and
preserve the host's intended allowlisting policy.

For native RHEL SSG playbook execution, a root-owned private directory such as
`/var/tmp/ansible-benchmark` can be selected with `ANSIBLE_REMOTE_TMP`. Inspect
SELinux denials and file labels if configuration validation fails. Do not
remove `validate` or switch SELinux off to bypass the underlying failure.

### Structured output contaminated by diagnostics

Ansible's `script` action can use a PTY. Login/PAM diagnostics may become mixed
with a helper's JSON output. A suitable alternative is `command` with an
explicit argument list and script input on stdin, keeping stdout and stderr
separate. Parse the result and retain failures. Retrying a deterministic
formatting problem will not fix it.

See [Ansible SSH connection options](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/ssh_connection.html)
and [the command module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/command_module.html).

## Controller checks

```bash
sudo python3 scripts/check-controller.py
sudo systemctl status semaphore postgresql@16-main --no-pager  # Ubuntu
sudo systemctl status semaphore postgresql --no-pager          # Enterprise Linux
sudo journalctl -u semaphore -n 100 --no-pager
sudo ss -lntp
free -h
df -h
```

`port_3000_listening` or `port_5432_listening` false means Semaphore or
PostgreSQL is not listening at all, so read that unit's status and journal;
`port_3000_only_loopback` or `port_5432_only_loopback` false means it listens
beyond loopback. On Ubuntu, `postgresql_is_active` checks the cluster unit
`postgresql@16-main`, because the `postgresql` unit is a wrapper that stays
active while the cluster is down.

Read logs locally and sanitize them before sharing. A successful `/api/ping`
response verifies an HTTP endpoint; follow it with an authenticated login and
an actual task. If a configured proxy is involved, verify its loopback bind,
upstream, original Host header and WebSocket forwarding. The direct SSH tunnel
does not require a reverse proxy.

## Installer interrupted or failed

The installer is intentionally one-time and refuses existing state. Preserve
its error and inspect which stages completed. On a disposable fresh VM, a
rebuild from the clean baseline may be simplest. If data or credentials now
matter, use the manual stage/recovery procedure; do not remove the ownership
files or database just to make the installer run again.

Both installers download and check the Semaphore archive, and build
`/opt/ansible-venv`, before they create any state they refuse on a rerun. A
checksum mismatch deletes the download, and a failed `pip install` removes the
new virtual environment; fix the cause and run `--apply` again. The Ubuntu
installer installs PostgreSQL 16 after the virtual environment. If that install
fails before it creates `/etc/postgresql` or `/var/lib/postgresql`, it also
removes the new `/opt/ansible-venv`, so fix the cause and run `--apply` again;
if it fails after creating either, it says that a rerun would be refused, and
the rebuild or manual procedure above applies. With either installer, if the
`semaphore` account cannot read the lab folder, the installer stops before
seeding and prints the `seed-semaphore.py` command to run once the permissions
are fixed.

On a new Ubuntu VM, unattended upgrades can hold apt's locks for minutes. The
Ubuntu installer and `expose-semaphore.sh` wait up to ten minutes for the
package lock and retry `apt-get update` every 10 seconds, up to 30 times,
printing `apt-get update failed; another apt process may hold its lock.
Retrying in 10 seconds.` Let them wait.

With `--expose`, the controller is installed and seeded before the exposure
step. If `expose-semaphore.sh` or the readiness check after it fails, the
installer still prints its next steps, then `Only the --expose MODE step
failed. Do not run the installer again` with the two commands to run once the
cause shown above them is fixed, and exits with status 1.

Do not change a release checksum to match an unexpected download. Verify the
release, architecture and authenticated source first.

## Controller update stopped

`scripts/update-controller.sh` stops before changing anything it should not,
and its message names the fix:

| Message | Next step |
| --- | --- |
| `No lab folder at ...; pass the --lab-dir the installer used.` | Rerun with `--lab-dir` set to the folder the installer used. |
| `Plan only. Resolve the N problem(s) above before you run it with --apply.` | Each problem line above says what to do; the plan exits with status 1 while any remains. |
| An uncommitted change to a guide file | When `.guide-files.json` is among the files, an earlier update wrote them and stopped before its commit: commit them together. Otherwise commit your own edit, or discard what an interrupted update wrote. |
| `Writing the guide's files stopped ...` | The update put back what it had written. Fix the cause, such as a full disk or an editor saving the file, and run it again. |
| `The password was accepted, but Semaphore also wants a second factor` | Pass an administrator's API token as `SEMAPHORE_API_TOKEN`; see [update a controller](03-controller.md#update-a-controller-to-a-newer-guide-release). |
| `... may not change the templates of project ...` | Use an administrator's login or token, or the project owner's or a manager's. |
| `Kept template ...: schedule ... runs it` | Move those schedules or integrations to the per-system templates, then run `--apply --remove-replaced` again. |
| `... failed with HTTP NNN: REASON` | The text after the colon is Semaphore's own reason. |

## Benchmark result surprises

A completed scan with failed or manual controls is a result to investigate,
not a parser failure. An error, unknown outcome, empty result set, or a result
in which every rule is `notselected` is an assessment-quality problem: for the
last, check the profile ID with `oscap info FILE` or `usg list`. When a scan
stops with `The vendor scanner produced no results`, on Ubuntu the message
gives `usg`'s exit code and the end of its output; if `usg` rejected the
profile, set `stig_usg_profile` to an ID that `usg list` shows, as
[the security baseline catalog](appendices/security-baselines.md) explains. New packages can make more rules applicable, and
one rule can contain many result instances. Use [the benchmark guide](09-security-benchmarks.md)
and the original XML instead of relying on a green job label or a simple ratio.

## Before asking for help

Prepare a sanitized description of the expected outcome, the exact command or
template, software versions, selected target/ref, and the first relevant error.
Share only the minimum necessary output. Never include a private key, password,
token, configuration dump, database backup or unsanitized inventory.
