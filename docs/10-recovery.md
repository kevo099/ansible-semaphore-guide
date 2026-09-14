# 10. Backup, restore and rebuild

[Previous: benchmarks](09-security-benchmarks.md) · [Next: troubleshooting](11-troubleshooting.md)

## Goal

Recover both the application and its ability to run an authenticated job,
without depending on the machine or storage you are trying to recover.

## Know what each recovery layer protects

| Layer | Useful for | What it does not establish |
| --- | --- | --- |
| Git commit/tag | Recovering reviewed automation source | Database, secrets, ignored inventories or guest disks |
| Application backup | Recovering Semaphore configuration, database and encrypted credentials | The OS/runtime unless those are rebuilt separately |
| Local VM snapshot | Quickly undoing a controlled experiment on that storage | Survival of storage or host loss |
| Independent VM backup | Restoring a guest after losing its original storage | Application correctness until a restore is tested |
| Offsite/independent copy | Recovery from loss of the primary location or failure domain | Guaranteed recovery without integrity and restore checks |

Snapshots and backups have distinct retention, ownership and recovery
procedures. In Proxmox, a VM backup does not preserve its complete local
snapshot tree. Retain installation media separately when needed. Consult
[Proxmox backup documentation](https://pve.proxmox.com/pve-docs/chapter-vzdump.html)
for the storage-specific behavior.

## Back up the pieces that belong together

For the guide's native controller, protect:

- The PostgreSQL `semaphore` database.
- `/etc/semaphore/config.json`, especially its database and encryption keys.
- The verified known-hosts file, Git configuration, private inventories and
  any additional runtime secrets actually used by your jobs.
- The systemd service and its drop-ins; any SSH/reverse-proxy configuration
  you added; the relevant PostgreSQL configuration.
- Exact application/Ansible versions and your playbook repository/ref.
- Your own Git repository and any encrypted host variables ignored by it.
- Your independent password-manager/recovery process for operator credentials.

The database and access-key encryption configuration must be a matching set.
Regenerating the encryption key does not recover existing encrypted Key Store
entries. Your initial-admin password file can become stale after a UI password
change; the restored database contains the current account state.

## A private application capture

**Where: controller.** Schedule a brief application maintenance window, pause
schedules/integrations and finish all running/queued jobs. Prevent new task
launches during the capture. The following example stops only Semaphore,
leaves PostgreSQL running for `pg_dump`, and restores the application's
previous running/stopped state on exit.

This base capture covers the paths shown. Add your separately documented
inventories, Git, external secrets and optional proxy/SSH configuration to the
private recovery set; do not assume they are all under these paths.

```bash
sudo bash <<'BASH'
set -euo pipefail
umask 077
backup_dir="/var/backups/semaphore-guide/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$backup_dir"
was_running=0
if systemctl is-active --quiet semaphore; then was_running=1; fi
finish_capture() {
  result=$?
  if [[ "$was_running" == 1 ]]; then
    if ! systemctl start semaphore; then
      echo 'Backup exit: Semaphore did not restart; inspect it locally.' >&2
      result=1
    fi
  fi
  exit "$result"
}
trap finish_capture EXIT
systemctl stop semaphore
runuser -u postgres -- pg_dump --format=custom semaphore > "$backup_dir/semaphore.dump"
config_paths=(etc/semaphore etc/systemd/system/semaphore.service etc/postgresql/16/main)
if [[ -d /etc/systemd/system/semaphore.service.d ]]; then
  config_paths+=(etc/systemd/system/semaphore.service.d)
fi
tar -C / -czf "$backup_dir/controller-config.tar.gz" "${config_paths[@]}"
{
  /usr/local/bin/semaphore version
  /opt/ansible-venv/bin/ansible --version
  runuser -u postgres -- psql -X -Atc 'SHOW server_version;'
} > "$backup_dir/runtime.txt"
cd "$backup_dir"
sha256sum semaphore.dump controller-config.tar.gz runtime.txt > SHA256SUMS
sha256sum --check SHA256SUMS
echo "Private capture complete: $backup_dir"
BASH
```

Check application readiness afterward and reopen normal job access only when
the owning checks pass:

```bash
sudo python3 scripts/check-controller.py
```

Copy the recovery set through an authenticated encrypted path to independently
protected storage, then verify its checksum manifest at the destination. Do
not copy it into this repository, a public issue, a CI artifact or a shared
unprotected folder. Encryption at rest and access restrictions depend on your
chosen backup destination; a checksum provides integrity checking, not secrecy.

For your own Git working repository, a separate private bundle can preserve
all committed refs:

```bash
umask 077
install -d -m 0700 ~/private-backups
git bundle create ~/private-backups/ansible-playbooks.bundle --all
git bundle verify ~/private-backups/ansible-playbooks.bundle
```

Give subsequent bundles distinct names or an explicit retention policy. A
bundle does not include ignored files or uncommitted changes.

## Restore first into an isolated replacement

The following is a rehearsal procedure, not an instruction to overwrite your
running controller. Use a new VM with enough storage and an isolated network.
Allow administration, but **block its access to the original managed targets**.
A restored database may contain schedules and integrations that attempt jobs
as soon as the application starts.

1. Verify the backup manifest before using the archive. Inspect its file list
   privately and use only a recovery set you trust.
2. Install the same Ubuntu, Python, Ansible, PostgreSQL and Semaphore versions.
   Use manual steps 1–2 for the runtime, the account/directory commands at the
   beginning of step 3, and step 5 for the binary. **Skip the configuration
   generator, empty-file creation and application initialization.** Do not
   generate replacement encryption keys, create a new admin or start Semaphore.
3. Restore the backed-up `/etc/semaphore` files into the new controller. Reapply
   `root:semaphore` ownership and the documented private modes. Restore the
   service unit/drop-ins and review the PostgreSQL configuration for this VM.
   Extract the archive into a private staging directory first; do not blindly
   unpack an entire machine's configuration over a different host.
   Numeric account IDs can differ on the replacement, so set ownership by the
   account names rather than trusting the archived numeric IDs.
4. Start the new PostgreSQL 16 cluster. Recreate the dedicated database role
   with the password from the restored private configuration, and create an
   empty database owned by that role.
5. Restore the dump into that empty database, with errors stopping the restore.
6. Restore the reviewed source and any privately held inventory/Vault files.
   Validate their paths and permissions for the unprivileged service user.
7. Keep network isolation while starting Semaphore. Confirm login and disable
   restored schedules/integrations before allowing any target access.
8. Point one test inventory at a disposable recovery target and run a real
   authenticated, non-changing job. Check sudo separately if it is required.

### Recreate the database role

If your configuration still uses the guide's generated 48-character hex
database password, the helper reads it without printing it:

```bash
sudo python3 scripts/create-database.py
```

It refuses an existing role/database. If you have rotated credentials or
changed the schema owner, follow your own recorded database procedure. For
example, create the role in a private interactive `psql` session and use
`\password semaphore` to enter the matching credential without a literal
password in SQL history.

### Restore the data

Stage the verified dump privately so the PostgreSQL account can read it. On
the isolated replacement only:

```bash
sudo install -o postgres -g postgres -m 0600 /PRIVATE/STAGING/semaphore.dump \
  /var/lib/postgresql/semaphore-restore.dump
sudo -u postgres pg_restore --exit-on-error --single-transaction \
  --no-owner --role=semaphore --dbname=semaphore \
  /var/lib/postgresql/semaphore-restore.dump
sudo -u postgres psql -X -d semaphore -c 'ANALYZE;'
```

The destination database must be empty. This procedure does not drop or clean
an existing database. If restoration fails, investigate the isolated copy;
do not retry destructive options against the original controller.

A dump does not automatically create all cluster-wide roles. PostgreSQL's
[dump documentation](https://www.postgresql.org/docs/16/backup-dump.html) and
[`pg_restore` reference](https://www.postgresql.org/docs/16/app-pgrestore.html)
explain ownership, format and version requirements.

## What to verify after restoration

Check the application version, database schema and expected projects/templates.
Compare actual table counts or other recorded data checks with the capture.
Then confirm a real job can use the restored encrypted SSH credential and,
where needed, its sudo/Vault credential. A login page alone is not sufficient.

For a full VM restore, also verify boot, storage, unique network placement,
guest services, console access and the SSH host-key trust decision. Decide
whether the restore replaces the original identity or is a separate isolated
test; do not connect two copies with conflicting identities to the same network.

Record what was actually tested: a database restore on the same machine, a
replacement controller, a VM backup restore and an offsite recovery are
different exercises. Remove only your explicitly identified temporary recovery
copies after the drill, keeping the retained backup according to its policy.

## Rebuild a disposable target

Finish its jobs, select the exact guest, shut it down gracefully and use your
hypervisor's documented rollback or recreation procedure. Verify identity,
networking, host keys, automation access and sudo before resuming playbooks.
Snapshots taken before a key/password change may require the corresponding
older recovery credentials. Keep that relationship in your private records.

## Concept

A backup is useful when you can identify it, trust its contents, recover its
secrets and prove that the restored system performs its intended work.
