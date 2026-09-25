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
- On the Enterprise Linux controller, its lab folder: the seeded project's
  playbooks, inventory and any Vault files.
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

The capture is written for both controllers, although only the Ubuntu one has
been tested. On the [Enterprise Linux controller](03-controller-el9.md) it
records PostgreSQL's `postgresql.conf` and `pg_hba.conf` from
`/var/lib/pgsql/data` instead of `/etc/postgresql/16/main`, and the lab folder
`/opt/ansible-lab`. If you installed with `--lab-dir`, add that path to the
`for extra in` list.

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
config_paths=(etc/semaphore etc/systemd/system/semaphore.service)
# Ubuntu keeps PostgreSQL's settings in /etc/postgresql; Enterprise Linux keeps
# them in its data directory. A missing file stops tar and the capture.
if [[ -d /etc/postgresql/16/main ]]; then
  config_paths+=(etc/postgresql/16/main)
else
  config_paths+=(var/lib/pgsql/data/postgresql.conf var/lib/pgsql/data/pg_hba.conf)
fi
# Optional: service drop-ins and the Enterprise Linux lab folder.
for extra in /etc/systemd/system/semaphore.service.d /opt/ansible-lab; do
  if [[ -e "$extra" ]]; then config_paths+=("${extra#/}"); fi
done
tar -C / -czf "$backup_dir/controller-config.tar.gz" "${config_paths[@]}"
{
  /usr/local/bin/semaphore version
  /opt/ansible-venv/bin/ansible --version
  /opt/ansible-venv/bin/python -m pip freeze --all
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
   Compare `/opt/ansible-venv/bin/python -m pip freeze --all` with the package
   list in the captured `runtime.txt`.
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

These steps and the commands below restore an Ubuntu controller onto an
Ubuntu replacement, which is the drill recorded in [validation](VALIDATION.md).
For a capture from the [Enterprise Linux controller](03-controller-el9.md),
use a replacement with the same Enterprise Linux release and change these
parts. This variant has not been run:

- Step 2 has no manual chapter. Do not run `install-controller-el9.sh`: it
  generates new secrets, creates an administrator and seeds a new project.
  Take the commands from its steps 2 and 3, the `useradd` and `install -d`
  lines of steps 4–5, `postgresql-setup --initdb` from step 6, and the binary
  with its `restorecon` from step 7.
- The PostgreSQL unit is `postgresql`, not `postgresql@16-main`. Its settings
  are `postgresql.conf` and `pg_hba.conf` in `/var/lib/pgsql/data`, found
  under `var/lib/pgsql/data` in the archive. Install those two as
  `postgres:postgres` with mode 0600 instead of the `conf.d` and `pg_hba.conf`
  commands below, then run `sudo restorecon -F` on them.
- `/etc/semaphore` also holds the `svc_ansible` key pair. Install both as
  `root:root`: `svc_ansible` with mode 0600 and `svc_ansible.pub` with mode
  0644.
- Stage the dump under `/var/lib/pgsql` instead of `/var/lib/postgresql`.
- Restore the lab folder to the same path, because the restored repository
  and inventory point there. Give it your administrator account as owner and
  the `semaphore` group, mode 2750 on its folders and 0640 on its files, as
  the installer does, then run `sudo restorecon -RF` on it.

On either system, `expose-semaphore.sh` keeps an `exposure` marker and a
`tls/` folder in `/etc/semaphore`. The commands below do not restore them, so
the replacement starts with the UI on loopback only. A capture taken in `http`
mode also binds Semaphore to every address in its `config.json`; the block
below sets it back to loopback in the staged copy before installing it.
Without that, `check-controller.py` reports
`semaphore_bind_matches_exposure_loopback: false`, and the restored Semaphore
listens on the network during the isolated rehearsal. Once the replacement has
passed its checks, run that script again with the mode you want.

### Restore the configuration files

After step 2, with the verified recovery set staged privately, extract the
configuration archive into its own staging directory and install each file by
account name with its documented mode. Review the PostgreSQL files first; they
belong only on a replacement with the same PostgreSQL major version:

```bash
umask 077
install -d -m 0700 ~/private-staging/config
tar -C ~/private-staging/config -xzf /PRIVATE/STAGING/controller-config.tar.gz
c=~/private-staging/config/etc
# A capture taken in http mode binds every address; start on loopback.
python3 - "$c/semaphore/config.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
config = json.loads(path.read_text())
config["interface"] = "127.0.0.1"
path.write_text(json.dumps(config, indent=2) + "\n")
PY
for f in config.json known_hosts gitconfig; do
  sudo install -o root -g semaphore -m 0640 "$c/semaphore/$f" "/etc/semaphore/$f"
done
sudo install -o root -g root -m 0600 "$c/semaphore/initial-admin-password" \
  /etc/semaphore/initial-admin-password
sudo install -o root -g root -m 0600 "$c/semaphore/.initial-admin-created" \
  /etc/semaphore/.initial-admin-created
sudo install -o root -g root -m 0644 "$c/systemd/system/semaphore.service" \
  /etc/systemd/system/semaphore.service
sudo install -o postgres -g postgres -m 0644 \
  "$c/postgresql/16/main/conf.d/ansible-guide.conf" \
  /etc/postgresql/16/main/conf.d/ansible-guide.conf
sudo install -o postgres -g postgres -m 0640 "$c/postgresql/16/main/pg_hba.conf" \
  /etc/postgresql/16/main/pg_hba.conf
sudo systemctl restart postgresql@16-main
```

The `.initial-admin-created` marker stops the admin helper from creating a
second first administrator; the restored database already contains the
accounts.

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
