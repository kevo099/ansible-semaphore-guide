#!/usr/bin/env bash
# One-time bootstrap for a fresh Ubuntu 24.04 amd64 controller.
# No arguments or --plan: print the plan only. --apply: install on this VM.
set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
Usage: sudo bash scripts/install-controller.sh [--plan | --apply [--editor USER] [--lab-dir DIR] [--expose https|http]]

Creates a native Semaphore 2.19.12 / PostgreSQL 16 / Ansible 2.21.4 controller
on a fresh Ubuntu 24.04 amd64 VM, then seeds Semaphore with a project that runs
the guide playbooks from a local folder on this VM. It does not create VMs or
targets.

  --editor USER   Owner of the local lab folder (default: the sudo caller).
  --lab-dir DIR   Absolute path of the local lab folder (default: /opt/ansible-lab).
                  Not under /home, /root, /run/user, /tmp, /var/tmp or
                  /var/lib/semaphore, which the hardened service cannot read.
                  Pass the same --lab-dir to scripts/add-target.sh.
  --expose MODE   Also make the UI reachable on this VM's address: https (nginx TLS on
                  port 443, recommended) or http (plain text on port 3000). Default: the UI
                  stays loopback-only for SSH tunnels; scripts/expose-semaphore.sh can change it later.

The default is a read-only plan. --apply requires root and refuses existing
Semaphore, PostgreSQL, lab-folder or /opt/ansible-venv state. It installs
software and starts services. It creates fresh secrets locally and never
prints them. Semaphore and PostgreSQL listen on loopback. Target host keys
and the automation public key must still be installed before a job can run;
see scripts/add-target.sh and docs/03-controller.md.
USAGE
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
controller_family=deb
# shellcheck source=scripts/controller-common.sh
source "$script_dir/controller-common.sh"
controller_parse_args "$@"

if [[ "$mode" == --plan ]]; then
  usage
  cat <<'PLAN'

Plan:
  1. Check for a fresh Ubuntu 24.04 VM, the architecture, the lab folder path
     and the absence of state.
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
 10. Generate the svc_ansible automation key pair (public key is printed as a path).
 11. Copy the guide playbooks, including the vendor STIG lessons, and the report
     summarizer into the local lab folder with an empty inventory. A .gitignore
     keeps inventories/, host_vars/ and group_vars/ out of the folder's Git
     history. Confirm the semaphore account can read the inventory.
 12. Seed Semaphore through its API: project, keys, local folder repository,
     file inventory, variable groups and twelve scoped task templates on the
     tabs Lessons, Patching and STIG.
 13. With --expose, publish the UI on this VM's address (TLS proxy or plain HTTP).
PLAN
  exit 0
fi

[[ $(id -u) == 0 ]] || { echo 'Run --apply with sudo on the new controller VM.'; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Requires Ubuntu 24.04.'; exit 1; }
[[ $(dpkg --print-architecture) == amd64 ]] || { echo 'The pinned binary requires amd64.'; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'Requires a VM running systemd.'; exit 1; }

controller_validate_lab
controller_require_fresh_state /etc/postgresql /var/lib/postgresql
controller_check_sources semaphore.service

# 2. Packages that create nothing the preflight refuses, then the pinned Semaphore archive.
#    A failed download or checksum leaves nothing that blocks a rerun.
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3.12 python3.12-venv git curl tar openssh-client ca-certificates
# Fetch PostgreSQL now but install it after the runtime: installing it creates
# /etc/postgresql and /var/lib/postgresql, which the preflight refuses.
apt-get install -y --download-only postgresql-16
controller_download
controller_install_runtime
apt-get install -y postgresql-16
[[ $(cat /var/lib/postgresql/16/main/PG_VERSION) == 16 ]] || { echo 'Expected PostgreSQL 16 main cluster.'; exit 1; }

controller_configure_account

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

controller_start semaphore.service
controller_seed_lab
controller_finish
