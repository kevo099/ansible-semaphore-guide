#!/usr/bin/env bash
# One-time bootstrap for a fresh RHEL, AlmaLinux or Rocky Linux 9.4 or later x86_64 controller.
# No arguments or --plan: print the plan only. --apply: install on this VM.
set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
Usage: sudo bash scripts/install-controller-el9.sh [--plan | --apply [--editor USER] [--lab-dir DIR] [--expose https|http]]

Creates a native Semaphore 2.19.12 / PostgreSQL 16 / Ansible 2.21.4 controller
on a fresh RHEL, AlmaLinux or Rocky Linux 9.4 or later x86_64 VM, then seeds
Semaphore with a project that runs the guide playbooks from a local folder on
this VM. RHEL must be registered with BaseOS and AppStream enabled. It does
not create VMs or targets.

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
see scripts/add-target.sh and docs/03-controller-el9.md.
USAGE
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
controller_family=el
# shellcheck source=scripts/controller-common.sh
source "$script_dir/controller-common.sh"
controller_parse_args "$@"

if [[ "$mode" == --plan ]]; then
  usage
  cat <<'PLAN'

Plan:
  1. Check for a fresh Enterprise Linux 9.4 or later VM, the architecture, the
     lab folder path and the absence of state.
  2. Install Python 3.12, Git, SSH client, SELinux tools and PostgreSQL 16, then
     download and SHA-256-check the pinned Semaphore Community archive before
     any state is created.
  3. Create /opt/ansible-venv from requirements-controller.txt, which pins
     every package.
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
     file inventory, variable groups and twelve scoped task templates.
 13. With --expose, publish the UI on this VM's address (TLS proxy or plain HTTP).
PLAN
  exit 0
fi

[[ $(id -u) == 0 ]] || { echo 'Run --apply with sudo on the new controller VM.'; exit 1; }
source /etc/os-release
case "$ID" in
  rhel|almalinux|rocky) ;;
  *) echo 'Requires RHEL, AlmaLinux or Rocky Linux 9.4 or later.'; exit 1 ;;
esac
# python3.12 and the postgresql:16 module stream first appear in the 9.4 AppStream.
if [[ ! "$VERSION_ID" =~ ^9\.([0-9]+)$ ]] || (( 10#${BASH_REMATCH[1]} < 4 )); then
  echo "Requires Enterprise Linux 9.4 or later for python3.12 and the postgresql:16 stream; found $VERSION_ID."
  echo 'Update an older VM (sudo dnf -y upgrade, then reboot) and run the installer again.'
  echo 'On RHEL, register the system with BaseOS and AppStream enabled first.'
  exit 1
fi
[[ $(uname -m) == x86_64 ]] || { echo 'The pinned binary requires x86_64.'; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'Requires a VM running systemd.'; exit 1; }
controller_validate_lab
controller_require_fresh_state /var/lib/pgsql/data/PG_VERSION
controller_check_sources semaphore-el9.service

# 2. Packages that create nothing the preflight refuses, then the pinned Semaphore archive.
#    A failed download or checksum leaves nothing that blocks a rerun.
dnf -y install python3.12 python3.12-pip git curl tar openssh-clients \
  policycoreutils-python-utils ca-certificates
dnf -y module enable postgresql:16
dnf -y module install postgresql:16/server
controller_download
controller_install_runtime
controller_configure_account

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

controller_start semaphore-el9.service
controller_seed_lab
controller_finish
