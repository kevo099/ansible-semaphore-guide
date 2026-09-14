# 8. Patching and daily operation

[Previous: Git and VS Code](07-git-and-vscode.md) · [Next: security benchmarks](09-security-benchmarks.md)

## Goal

Operate the lab deliberately: know which hosts a job will touch, understand its
maintenance effects, and verify the result beyond the job's exit status.

## A normal practice session

1. Check the hypervisor's current guest state and capacity. Start only the lab
   guests you own, using your platform's normal controls.
2. Confirm the controller, database and private browser tunnel are ready.
3. Check Semaphore for running or queued tasks. Verify the selected repository
   ref, inventory, target limit and variable group.
4. Run a connectivity check before a configuration job.
5. Inspect the complete result, then verify the intended target behavior.
6. Finish jobs before stopping guests. Stop targets first, then the controller,
   using graceful shutdown rather than a forced power cut.

An application service being enabled does not require its VM to run all day.
Keep VM power scheduling separate from package/service configuration and from
Semaphore's job schedules.

## Patching one target at a time

**Where: controller.** Establish a usable recovery point and a maintenance
window before package changes. Read [`patch.yml`](../playbooks/patch.yml).

```bash
ansible-playbook playbooks/patch.yml --limit lab-ubuntu --list-hosts
ansible-playbook playbooks/patch.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K --check --diff
ansible-playbook playbooks/patch.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K
```

The lesson performs normal repository upgrades. On Ubuntu, it refuses an
upgrade transaction requiring automatic removal. On Alma/RHEL, it checks DNF's
reboot-advice result and treats unexpected errors as errors. It is not labelled
“security-only”: that claim would require the repository metadata and package
manager's supported security-selection behavior.

`serial: 1` applies the play to one host at a time, and `any_errors_fatal: true`
prevents continuing to later hosts after a failed batch. With different sudo
passwords, the beginner path remains separate single-target jobs.

### Reboot explicitly

On the target, record the current boot ID before the planned operation:

```bash
cat /proc/sys/kernel/random/boot_id
```

Then, from the controller:

```bash
ansible-playbook playbooks/patch.yml --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K -e '{"allow_reboot":true}'
```

The playbook reboots only if the OS reports that a reboot is needed. If none is
needed, an unchanged boot ID is expected. For a deliberate forced reboot
exercise, write a separately named playbook, make the choice explicit, and
include connection and application checks. Do not hide power actions in a
connectivity or audit job.

**Check after a reboot:**

```bash
cat /proc/sys/kernel/random/boot_id
systemctl --failed
systemctl is-active chrony
curl --fail http://127.0.0.1:8080/
```

Use `chronyd` on Alma/RHEL and run the HTTP check only if the web lesson is
installed. Check direct SSH, sudo and the managed service as appropriate.
Ansible reconnecting proves SSH returned; it does not prove an application is
ready for users.

## Introduce drift carefully

Choose one file owned by a lesson, such as `/etc/motd`. Save its expected
content, change it on a disposable target, then preview and apply the owning
playbook. Confirm that only the expected task changes and that the next run
converges.

A drift audit and a drift repair are different workflows. An audit should
collect evidence without applying configuration. A repair should name the
desired state and its owner. Do not automatically remediate every difference
from another machine; some differences are intentional.

Useful read-only checks for later exercises include:

- SSH public-key fingerprints and effective `sshd` policy.
- Listening sockets and their bound addresses.
- Privileged account/group membership.
- Certificate parsing, subject/issuer and expiration.
- Failed services and pending package/reboot state.

When you write an Ansible audit with `command`, set `changed_when: false` for
read-only commands and check their exit codes. Do not declare success merely
because a helper produced some text. Structured output should be parsed and
validated; diagnostics belong on stderr.

## Add scheduling only after manual qualification

For a scheduled task, record its timezone, frequency, inventory, code ref,
maintenance scope and retry behavior. Check that the VM will actually be
running, that another task cannot overlap it, and that credentials remain
valid. Test the task manually under the service account first.

Start with an audit or connectivity check. Schedule patching only after its
recovery and application checks work. A missed schedule should not silently
reboot a target outside the intended maintenance window.

The example controller permits one application task at a time. Increase
concurrency only after measuring CPU, available RAM, storage and per-job
behavior; free-looking memory during a ping does not size a fleet-wide scanner.

## Inspect resource and retention growth

**Where: controller.**

```bash
free -h
df -h / /var/lib/postgresql /var/lib/semaphore
sudo du -sh /var/lib/semaphore /var/lib/postgresql
sudo journalctl -u semaphore --since today --no-pager
```

Job logs and reports can contain operational data or accidentally echoed
secrets. Keep them private, define retention, and review them before sharing.
Use the application and database's supported retention procedures. Deleting
the database volume is not a password reset or a log cleanup procedure.

## Check

You can explain what ran, which hosts it affected, whether a reboot happened,
what changed, how application readiness was confirmed, and which recovery
point would be used if the change failed.

## Concept

Reliable automation includes the action and its evidence. Scope, maintenance,
error handling, repeatability and recovery are part of the workflow, not tasks
to add only after an incident.
