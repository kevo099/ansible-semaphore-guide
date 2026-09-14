#!/usr/bin/env bash
# One-time bootstrap for a fresh RHEL 9, AlmaLinux 9 or Rocky Linux 9 x86_64 controller.
# No arguments or --plan: print the plan only. --apply: install on this VM.
set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
Usage: sudo bash scripts/install-controller-el9.sh [--plan | --apply [--editor USER] [--lab-dir DIR]]

Creates a native Semaphore 2.19.12 / PostgreSQL 16 / Ansible 2.20.8 controller
on a fresh Enterprise Linux 9 x86_64 VM, then seeds Semaphore with a project
that runs the guide playbooks from a local folder on this VM. It does not
create VMs or targets.

  --editor USER   Owner of the local lab folder (default: the sudo caller).
  --lab-dir DIR   Absolute path of the local lab folder (default: /opt/ansible-lab).

The default is a read-only plan. --apply requires root and refuses existing
Semaphore, PostgreSQL, lab-folder or /opt/ansible-venv state. It installs
software and starts services. It creates fresh secrets locally and never
prints them. Semaphore and PostgreSQL listen on loopback. Target host keys
and the automation public key must still be installed before a job can run;
see scripts/add-target.sh and docs/03-controller-el9.md.
USAGE
}

mode=--plan
editor="${SUDO_USER:-}"
lab_dir=/opt/ansible-lab
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --plan|--apply) mode="$1" ;;
    --editor) [[ $# -ge 2 ]] || { usage; exit 2; }; editor="$2"; shift ;;
    --lab-dir) [[ $# -ge 2 ]] || { usage; exit 2; }; lab_dir="$2"; shift ;;
    *) usage; exit 2 ;;
  esac
  shift
done

if [[ "$mode" == --plan ]]; then
  usage
  cat <<'PLAN'

Plan:
  1. Check the fresh Enterprise Linux 9 VM, architecture and absence of state.
  2. Install Python 3.12, Git, SSH client, SELinux tools and PostgreSQL 16.
  3. Create /opt/ansible-venv with pinned ansible-core.
  4. Create the unprivileged semaphore service account.
  5. Generate /etc/semaphore/config.json and the initial admin password.
  6. Create a dedicated PostgreSQL role/database with local SCRAM authentication.
  7. Download and SHA-256-check the pinned Semaphore Community archive.
  8. Run schema migrations and create the first admin account.
  9. Install the restricted systemd service and check loopback readiness.
 10. Generate the svc_ansible automation key pair (public key is printed as a path).
 11. Copy the guide playbooks, including the vendor STIG lessons, and the report
     summarizer into the local lab folder with an empty inventory.
 12. Seed Semaphore through its API: project, keys, local folder repository,
     file inventory, variable groups and eleven scoped task templates.
PLAN
  exit 0
fi

[[ $(id -u) == 0 ]] || { echo 'Run --apply with sudo on the new controller VM.'; exit 1; }
source /etc/os-release
case "$ID" in
  rhel|almalinux|rocky) ;;
  *) echo 'Requires RHEL 9, AlmaLinux 9 or Rocky Linux 9.'; exit 1 ;;
esac
[[ "${VERSION_ID%%.*}" == 9 ]] || { echo 'Requires an Enterprise Linux 9 release.'; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'The pinned binary requires x86_64.'; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'Requires a VM running systemd.'; exit 1; }
[[ "$lab_dir" == /* && "$lab_dir" != "/" ]] || { echo 'The lab folder must be an absolute path.'; exit 1; }
[[ -n "$editor" ]] || { echo 'Pass --editor USER when not running through sudo.'; exit 1; }
getent passwd "$editor" >/dev/null || { echo "Editor account does not exist: $editor"; exit 1; }
[[ "$editor" != root && "$editor" != semaphore ]] || { echo 'Choose a normal administrator as the editor.'; exit 1; }

for path in /etc/semaphore /opt/ansible-venv /usr/local/bin/semaphore \
            /var/lib/semaphore /var/lib/pgsql/data/PG_VERSION \
            /etc/systemd/system/semaphore.service "$lab_dir"; do
  [[ ! -e "$path" && ! -L "$path" ]] || { echo "Existing state: $path. Use the recovery guide, not this fresh installer."; exit 1; }
done
if command -v semaphore >/dev/null; then
  echo 'Semaphore is already on PATH; refusing to replace an existing installation.'
  exit 1
fi
if getent passwd semaphore >/dev/null; then
  echo 'The semaphore account already exists; refusing to reuse it.'
  exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
for path in controller_config.py create-database.py create-admin.py check-controller.py seed-semaphore.py; do
  [[ -f "$script_dir/$path" ]] || { echo "Missing helper: $path"; exit 1; }
done
[[ -f "$repo_dir/templates/semaphore-el9.service" ]] || { echo 'Missing service template.'; exit 1; }
[[ -d "$repo_dir/playbooks" && -f "$repo_dir/ansible.cfg" ]] || { echo 'Missing guide playbooks.'; exit 1; }

# 2-3. Runtime
dnf -y install python3.12 python3.12-pip git curl tar openssh-clients \
  policycoreutils-python-utils ca-certificates
dnf -y module enable postgresql:16
dnf -y module install postgresql:16/server
python3.12 -m venv /opt/ansible-venv
/opt/ansible-venv/bin/pip install --disable-pip-version-check 'ansible-core==2.20.8'
chmod -R go+rX /opt/ansible-venv

# 4-5. Service account and private configuration
useradd --system --create-home --home-dir /var/lib/semaphore --shell /usr/sbin/nologin semaphore
install -d -o root -g semaphore -m 0750 /etc/semaphore
install -d -o semaphore -g semaphore -m 0700 /var/lib/semaphore /var/lib/semaphore/tmp
python3.12 "$script_dir/controller_config.py" --directory /etc/semaphore
chown root:semaphore /etc/semaphore/config.json
chmod 0640 /etc/semaphore/config.json
install -o root -g semaphore -m 0640 /dev/null /etc/semaphore/known_hosts
cat > /etc/semaphore/gitconfig <<GITCONFIG
[safe]
    directory = $lab_dir
GITCONFIG
chown root:semaphore /etc/semaphore/gitconfig
chmod 0640 /etc/semaphore/gitconfig

# 6. PostgreSQL 16 on loopback with SCRAM
postgresql-setup --initdb
[[ $(cat /var/lib/pgsql/data/PG_VERSION) == 16 ]] || { echo 'Expected a PostgreSQL 16 data directory.'; exit 1; }
cat >> /var/lib/pgsql/data/postgresql.conf <<'PGCONF'

# Settings for the dedicated guide controller only.
listen_addresses = 'localhost'
password_encryption = 'scram-sha-256'
PGCONF
python3.12 - <<'PY'
from pathlib import Path
p = Path('/var/lib/pgsql/data/pg_hba.conf')
original = p.read_text()
p.write_text(
    '# Dedicated Semaphore TCP login\n'
    'host semaphore semaphore 127.0.0.1/32 scram-sha-256\n'
    'host semaphore semaphore ::1/128 scram-sha-256\n' + original
)
PY
systemctl enable --now postgresql
systemctl restart postgresql
python3.12 "$script_dir/create-database.py"

# 7-9. Semaphore binary, schema, admin and service
install -d -m 0700 /var/cache/ansible-semaphore-guide
cd /var/cache/ansible-semaphore-guide
archive=semaphore_community_2.19.12_linux_amd64.tar.gz
digest=2576f8a473c5e91bd0d7833976111c56f0ad43720210f9ca437037d10acd97cc
curl --fail --location --retry 3 --output "$archive" \
  "https://github.com/semaphoreui/semaphore/releases/download/v2.19.12/$archive"
printf '%s  %s\n' "$digest" "$archive" | sha256sum --check --status
tar -xzf "$archive" semaphore
install -m 0755 semaphore /usr/local/bin/semaphore
restorecon -F /usr/local/bin/semaphore
runuser -u semaphore -- /usr/local/bin/semaphore migrate --config /etc/semaphore/config.json
python3.12 "$script_dir/create-admin.py"
install -o root -g root -m 0644 "$repo_dir/templates/semaphore-el9.service" /etc/systemd/system/semaphore.service
systemctl daemon-reload
systemctl enable --now semaphore

for attempt in {1..30}; do
  if curl -fsS -o /dev/null http://127.0.0.1:3000/api/ping; then break; fi
  sleep 1
done
python3.12 "$script_dir/check-controller.py"

# 10. Automation key pair. Unencrypted by explicit choice for an unattended lab;
#     the private key never leaves root-only storage except into the Key Store.
ssh-keygen -q -t rsa -b 4096 -N '' -C ansible-practice -f /etc/semaphore/svc_ansible
chmod 0600 /etc/semaphore/svc_ansible
chmod 0644 /etc/semaphore/svc_ansible.pub

# 11. Local lab folder owned by the editor, readable by the service
install -d -o "$editor" -g semaphore -m 2750 "$lab_dir" "$lab_dir/inventories"
cp -r "$repo_dir/playbooks" "$lab_dir/playbooks"
install -o "$editor" -g semaphore -m 0640 "$repo_dir/ansible.cfg" "$lab_dir/ansible.cfg"
install -d -o "$editor" -g semaphore -m 2750 "$lab_dir/scripts"
install -o "$editor" -g semaphore -m 0640 "$repo_dir/scripts/summarize_xccdf.py" "$lab_dir/scripts/summarize_xccdf.py"
cat > "$lab_dir/inventories/lab.ini" <<'INVENTORY'
# Local lab inventory read by Semaphore at every run. Add one line per target
# under the matching group, for example:
#   lab-ubuntu ansible_host=ubuntu.example.test
# Use scripts/add-target.sh to add a host together with its verified host key.
[ubuntu]

[enterprise_linux]

[lab:children]
ubuntu
enterprise_linux

[lab:vars]
ansible_user=svc_ansible
ansible_python_interpreter=/usr/bin/python3
INVENTORY
chown -R "$editor:semaphore" "$lab_dir"
runuser -u "$editor" -- git -C "$lab_dir" init -q -b main
runuser -u "$editor" -- git -C "$lab_dir" -c user.name=ansible-practice -c user.email=ansible-practice@example.test \
  add -A
runuser -u "$editor" -- git -C "$lab_dir" -c user.name=ansible-practice -c user.email=ansible-practice@example.test \
  commit -q -m 'Seed the local lab folder from the guide'
# Editor owns everything; the service only needs to read. Git history included, so a later
# push from this folder needs no permission changes.
find "$lab_dir" -type d -exec chmod 2750 {} +
find "$lab_dir" -type f -exec chmod 0640 {} +
restorecon -RF "$lab_dir"

# 12. Seed Semaphore through its API
python3.12 "$script_dir/seed-semaphore.py" --lab-dir "$lab_dir" \
  --key-file /etc/semaphore/svc_ansible --known-hosts /etc/semaphore/known_hosts

printf '\nController installed and seeded. Next: authorize the automation key on each target\n'
printf 'and add each target with its verified host key (scripts/add-target.sh).\n'
printf 'Automation public key: /etc/semaphore/svc_ansible.pub\n'
printf 'Local lab folder (edit as %s): %s\n' "$editor" "$lab_dir"
printf 'The initial admin password is in /etc/semaphore/initial-admin-password (root only).\n'
