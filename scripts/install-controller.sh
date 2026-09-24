#!/usr/bin/env bash
# One-time bootstrap for a fresh Ubuntu 24.04 amd64 controller.
# No arguments or --plan: print the plan only. --apply: install on this VM.
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: bash scripts/install-controller.sh [--plan | --apply]

Creates a native Semaphore 2.19.12 / PostgreSQL 16 / Ansible 2.20.8
controller on a fresh Ubuntu 24.04 amd64 VM. It does not create a VM.

The default is a read-only plan. --apply requires root and refuses existing
Semaphore, PostgreSQL or /opt/ansible-venv state. It installs software and
starts services. It creates fresh secrets locally and never prints them.
Semaphore and PostgreSQL listen on loopback. Target credentials and verified
SSH host keys must be configured separately before any job can run.
EOF
}

mode=${1:---plan}
[[ $# -le 1 ]] || { usage; exit 2; }
case "$mode" in
  --help|-h) usage; exit 0 ;;
  --plan)
    usage
    cat <<'EOF'

Plan:
  1. Check the fresh Ubuntu VM and architecture.
  2. Install Python 3.12, Git and SSH client, then download and SHA-256-check
     the pinned Semaphore Community archive before any state is created.
  3. Create /opt/ansible-venv from requirements-controller.txt, which pins
     every package, then install PostgreSQL 16.
  4. Create the unprivileged semaphore service account.
  5. Generate /etc/semaphore/config.json and the initial admin password.
  6. Create a dedicated PostgreSQL role/database with local SCRAM authentication.
  7. Install the checksum-verified Semaphore binary.
  8. Run schema migrations and create the first admin account.
  9. Install the restricted systemd service and check loopback readiness.
EOF
    exit 0
    ;;
  --apply) ;;
  *) usage; exit 2 ;;
esac

[[ $(id -u) == 0 ]] || { echo 'Run --apply with sudo on the new controller VM.'; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Requires Ubuntu 24.04.'; exit 1; }
[[ $(dpkg --print-architecture) == amd64 ]] || { echo 'The pinned binary requires amd64.'; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'Requires a VM running systemd.'; exit 1; }

for path in /etc/semaphore /opt/ansible-venv /usr/local/bin/semaphore \
            /var/lib/semaphore /etc/postgresql /var/lib/postgresql \
            /etc/systemd/system/semaphore.service; do
  [[ ! -e "$path" && ! -L "$path" ]] || {
    echo "Existing state: $path. This installer runs only on a fresh VM;"
    echo 'see docs/11-troubleshooting.md (Installer interrupted or failed).'
    exit 1
  }
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
for path in controller_config.py create-database.py create-admin.py check-controller.py; do
  [[ -f "$script_dir/$path" ]] || { echo "Missing helper: $path"; exit 1; }
done
[[ -f "$repo_dir/templates/semaphore.service" ]] || { echo 'Missing service template.'; exit 1; }
[[ -f "$repo_dir/requirements-controller.txt" ]] || { echo 'Missing requirements-controller.txt.'; exit 1; }

# 2. Packages that create nothing the preflight refuses, then the pinned Semaphore archive.
#    A failed download or checksum leaves nothing that blocks a rerun.
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3.12 python3.12-venv git curl tar openssh-client ca-certificates
# Fetch PostgreSQL now but install it after the runtime: installing it creates
# /etc/postgresql and /var/lib/postgresql, which the preflight refuses.
apt-get install -y --download-only postgresql-16
cache=/var/cache/ansible-semaphore-guide
archive=semaphore_community_2.19.12_linux_amd64.tar.gz
digest=2576f8a473c5e91bd0d7833976111c56f0ad43720210f9ca437037d10acd97cc
install -d -m 0700 "$cache"
curl --fail --location --retry 3 --output "$cache/$archive" \
  "https://github.com/semaphoreui/semaphore/releases/download/v2.19.12/$archive"
if ! printf '%s  %s\n' "$digest" "$cache/$archive" | sha256sum --check --status; then
  rm -f -- "$cache/$archive"
  echo "SHA-256 mismatch for $archive; deleted the download. Only packages were installed so far."
  echo 'Do not edit the pinned checksum. Check the network path (proxy, captive portal)'
  echo 'and the release, then rerun --apply.'
  exit 1
fi
tar -xzf "$cache/$archive" -C "$cache" semaphore

# 3. Controller runtime with every package pinned, then PostgreSQL 16. The
#    preflight proved /opt/ansible-venv did not exist, so a failed pip run can
#    remove it and the installer can be rerun.
if ! { python3.12 -m venv /opt/ansible-venv &&
       /opt/ansible-venv/bin/pip install --disable-pip-version-check \
         --requirement "$repo_dir/requirements-controller.txt"; }; then
  rm -rf /opt/ansible-venv
  echo 'Creating /opt/ansible-venv failed; removed the new directory. Fix the cause and rerun --apply.'
  exit 1
fi
chmod -R go+rX /opt/ansible-venv
apt-get install -y postgresql-16
[[ $(cat /var/lib/postgresql/16/main/PG_VERSION) == 16 ]] || { echo 'Expected PostgreSQL 16 main cluster.'; exit 1; }

# 4-5. Service account and private configuration
useradd --system --create-home --home-dir /var/lib/semaphore --shell /usr/sbin/nologin semaphore
install -d -o root -g semaphore -m 0750 /etc/semaphore
install -d -o semaphore -g semaphore -m 0700 /var/lib/semaphore /var/lib/semaphore/tmp
python3.12 "$script_dir/controller_config.py" --directory /etc/semaphore
chown root:semaphore /etc/semaphore/config.json
chmod 0640 /etc/semaphore/config.json
install -o root -g semaphore -m 0640 /dev/null /etc/semaphore/known_hosts
cat > /etc/semaphore/gitconfig <<'EOF'
[safe]
    directory = /opt/ansible-guide.git
EOF
chown root:semaphore /etc/semaphore/gitconfig
chmod 0640 /etc/semaphore/gitconfig

# 6. PostgreSQL 16 on loopback with SCRAM
cat > /etc/postgresql/16/main/conf.d/ansible-guide.conf <<'EOF'
# Settings for the dedicated guide controller only.
listen_addresses = 'localhost'
password_encryption = 'scram-sha-256'
EOF
chmod 0644 /etc/postgresql/16/main/conf.d/ansible-guide.conf
# Prepend rules specific to this database and role; retain distribution defaults.
python3.12 - <<'PY'
from pathlib import Path
p=Path('/etc/postgresql/16/main/pg_hba.conf')
original=p.read_text()
p.write_text(
    '# Dedicated Semaphore TCP login\n'
    'host semaphore semaphore 127.0.0.1/32 scram-sha-256\n'
    'host semaphore semaphore ::1/128 scram-sha-256\n' + original
)
PY
systemctl enable --now postgresql postgresql@16-main
systemctl restart postgresql@16-main
python3.12 "$script_dir/create-database.py"

# 7-9. Verified binary, schema, admin and service
cd "$cache"
install -m 0755 semaphore /usr/local/bin/semaphore
runuser -u semaphore -- /usr/local/bin/semaphore migrate --config /etc/semaphore/config.json
python3.12 "$script_dir/create-admin.py"
install -o root -g root -m 0644 "$repo_dir/templates/semaphore.service" /etc/systemd/system/semaphore.service
systemctl daemon-reload
systemctl enable --now semaphore

for attempt in {1..30}; do
  if curl -fs -o /dev/null http://127.0.0.1:3000/api/ping; then break; fi
  sleep 1
done
python3.12 "$script_dir/check-controller.py"
printf '\nController installed. Continue with SSH trust and the Semaphore UI guide.\n'
printf 'The initial admin password is in /etc/semaphore/initial-admin-password (root only).\n'
