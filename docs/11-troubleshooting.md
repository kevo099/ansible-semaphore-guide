# 11. Troubleshoot by layer

[Previous: recovery](10-recovery.md) · [Next: learning exercises](12-learning-path.md)

Start with the first failed layer: guest state → network → SSH trust → login
key → Python → sudo → module → application. Preserve the original error and
the exact code ref, inventory and execution context. Do not repeatedly reboot
or loosen security controls without understanding what failed.

## Common symptoms

| Symptom | Check first | Appropriate next step |
| --- | --- | --- |
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
| Package-manager lock | Another package update is active | Wait for the owning operation; do not delete lock files or kill it blindly. |
| Task appears finished but recap is incomplete | Output persistence and stream timing | Wait for the complete host recap, then inspect the actual failure. |
| Browser works but task is queued | Application concurrency and another running task | Check task state before launching duplicates. |
| Restored UI cannot decrypt keys | Matching database and access-key encryption configuration | Restore the matching private configuration; generating a new key will not decrypt the old records. |

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

Use `sshd` as the journal unit on Alma/RHEL. If access is broken, perform these
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
sudo systemctl status semaphore postgresql@16-main --no-pager
sudo journalctl -u semaphore -n 100 --no-pager
sudo ss -lntp
free -h
df -h
```

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

Do not change a release checksum to match an unexpected download. Verify the
release, architecture and authenticated source first.

## Benchmark result surprises

A completed scan with failed or manual controls is a result to investigate,
not a parser failure. An error, unknown outcome or empty result set is an
assessment-quality problem. New packages can make more rules applicable, and
one rule can contain many result instances. Use [the benchmark guide](09-security-benchmarks.md)
and the original XML instead of relying on a green job label or a simple ratio.

## Before asking for help

Prepare a sanitized description of the expected outcome, the exact command or
template, software versions, selected target/ref, and the first relevant error.
Share only the minimum necessary output. Never include a private key, password,
token, configuration dump, database backup or unsanitized inventory.
