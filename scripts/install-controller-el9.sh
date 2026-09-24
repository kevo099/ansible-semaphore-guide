#!/usr/bin/env bash
# One-time bootstrap for a fresh RHEL, AlmaLinux or Rocky Linux 9.4 or later x86_64 controller.
# No arguments or --plan: print the plan only. --apply: install on this VM.
set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
Usage: sudo bash scripts/install-controller-el9.sh [--plan | --apply [--editor USER] [--lab-dir DIR] [--expose https|http]]

Creates a native Semaphore 2.19.12 / PostgreSQL 16 / Ansible 2.20.8 controller
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

mode=--plan
editor="${SUDO_USER:-}"
lab_dir=/opt/ansible-lab
expose=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --plan|--apply) mode="$1" ;;
    --editor) [[ $# -ge 2 ]] || { usage; exit 2; }; editor="$2"; shift ;;
    --lab-dir) [[ $# -ge 2 ]] || { usage; exit 2; }; lab_dir="$2"; shift ;;
    --expose) [[ $# -ge 2 && ( "$2" == https || "$2" == http ) ]] || { usage; exit 2; }; expose="$2"; shift ;;
    *) usage; exit 2 ;;
  esac
  shift
done

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
     file inventory, variable groups and eleven scoped task templates.
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
[[ "$lab_dir" == /* ]] || { echo 'The lab folder must be an absolute path.'; exit 1; }
lab_dir=$(realpath -m -- "$lab_dir")
[[ "$lab_dir" != / ]] || { echo 'The lab folder must be below /.'; exit 1; }
# semaphore.service runs with ProtectHome=yes and PrivateTmp=yes, and its own home
# is private, so it cannot read a lab folder in any of these places.
case "$lab_dir/" in
  /home/*|/root/*|/run/user/*|/tmp/*|/var/tmp/*|/var/lib/semaphore/*)
    echo "The Semaphore service cannot read a lab folder at $lab_dir: not under /home, /root,"
    echo '/run/user, /tmp, /var/tmp or /var/lib/semaphore. Use a path such as the default'
    echo '/opt/ansible-lab or /srv/ansible-lab.'
    exit 1 ;;
esac
# The nearest existing parent must let other accounts through, or the service cannot
# reach the folder. Missing parents are created later with mode 0755.
lab_parent=$(dirname -- "$lab_dir")
while [[ ! -e "$lab_parent" ]]; do lab_parent=$(dirname -- "$lab_parent"); done
if [[ ! -d "$lab_parent" ]] || ! runuser -u nobody -- test -x "$lab_parent"; then
  echo "$lab_parent is not a folder other accounts can enter, so the Semaphore service"
  echo "could not read $lab_dir. Choose another path or fix that folder's permissions."
  exit 1
fi
[[ -n "$editor" ]] || { echo 'Pass --editor USER when not running through sudo.'; exit 1; }
getent passwd "$editor" >/dev/null || { echo "Editor account does not exist: $editor"; exit 1; }
[[ "$editor" != root && "$editor" != semaphore ]] || { echo 'Choose a normal administrator as the editor.'; exit 1; }

for path in /etc/semaphore /opt/ansible-venv /usr/local/bin/semaphore \
            /var/lib/semaphore /var/lib/pgsql/data/PG_VERSION \
            /etc/systemd/system/semaphore.service "$lab_dir"; do
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
for path in controller_config.py create-database.py create-admin.py check-controller.py seed-semaphore.py expose-semaphore.sh; do
  [[ -f "$script_dir/$path" ]] || { echo "Missing helper: $path"; exit 1; }
done
[[ -f "$repo_dir/templates/semaphore-el9.service" ]] || { echo 'Missing service template.'; exit 1; }
[[ -d "$repo_dir/playbooks" && -f "$repo_dir/ansible.cfg" ]] || { echo 'Missing guide playbooks.'; exit 1; }
[[ -f "$repo_dir/requirements-controller.txt" ]] || { echo 'Missing requirements-controller.txt.'; exit 1; }

# 2. Packages that create nothing the preflight refuses, then the pinned Semaphore archive.
#    A failed download or checksum leaves nothing that blocks a rerun.
dnf -y install python3.12 python3.12-pip git curl tar openssh-clients \
  policycoreutils-python-utils ca-certificates
dnf -y module enable postgresql:16
dnf -y module install postgresql:16/server
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

# 3. Controller runtime with every package pinned. The preflight proved
#    /opt/ansible-venv did not exist, so a failed pip run can remove it and the
#    installer can be rerun.
if ! { python3.12 -m venv /opt/ansible-venv &&
       /opt/ansible-venv/bin/pip install --disable-pip-version-check \
         --requirement "$repo_dir/requirements-controller.txt"; }; then
  rm -rf /opt/ansible-venv
  echo 'Creating /opt/ansible-venv failed; removed the new directory. Fix the cause and rerun --apply.'
  exit 1
fi
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

# 7-9. Verified binary, schema, admin and service
cd "$cache"
install -m 0755 semaphore /usr/local/bin/semaphore
restorecon -F /usr/local/bin/semaphore
runuser -u semaphore -- /usr/local/bin/semaphore migrate --config /etc/semaphore/config.json
python3.12 "$script_dir/create-admin.py"
install -o root -g root -m 0644 "$repo_dir/templates/semaphore-el9.service" /etc/systemd/system/semaphore.service
systemctl daemon-reload
systemctl enable --now semaphore

for attempt in {1..30}; do
  if curl -fs -o /dev/null http://127.0.0.1:3000/api/ping; then break; fi
  sleep 1
done
python3.12 "$script_dir/check-controller.py"

# 10. Automation key pair. Unencrypted by explicit choice for an unattended lab;
#     the private key never leaves root-only storage except into the Key Store.
ssh-keygen -q -t rsa -b 4096 -N '' -C ansible-practice -f /etc/semaphore/svc_ansible
chmod 0600 /etc/semaphore/svc_ansible
chmod 0644 /etc/semaphore/svc_ansible.pub

# 11. Local lab folder owned by the editor, readable by the service
(umask 022; mkdir -p -- "$(dirname -- "$lab_dir")")
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
# Semaphore reads the inventory from the working tree, so Git never needs it. Keep
# target addresses and Vault files out of the folder's history from the first commit.
printf '%s\n' 'inventories/' 'host_vars/' 'group_vars/' > "$lab_dir/.gitignore"
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
if ! runuser -u semaphore -- test -r "$lab_dir/inventories/lab.ini"; then
  echo "The semaphore account cannot read $lab_dir/inventories/lab.ini, so no template could run."
  echo "Nothing was seeded. Make $lab_dir and each parent folder readable to that account,"
  echo 'then seed Semaphore (and run expose-semaphore.sh if you chose --expose):'
  echo "  sudo python3.12 $script_dir/seed-semaphore.py --lab-dir $lab_dir \\"
  echo '    --key-file /etc/semaphore/svc_ansible --known-hosts /etc/semaphore/known_hosts'
  exit 1
fi

# 12. Seed Semaphore through its API
python3.12 "$script_dir/seed-semaphore.py" --lab-dir "$lab_dir" \
  --key-file /etc/semaphore/svc_ansible --known-hosts /etc/semaphore/known_hosts

# 13. Optional network exposure
if [[ -n "$expose" ]]; then
  bash "$script_dir/expose-semaphore.sh" --mode "$expose"
  python3.12 "$script_dir/check-controller.py"
fi

printf '\nController installed and seeded. Next: authorize the automation key on each target\n'
printf 'and add each target with its verified host key (scripts/add-target.sh --lab-dir %s).\n' "$lab_dir"
printf 'Automation public key: /etc/semaphore/svc_ansible.pub\n'
printf 'Local lab folder (edit as %s): %s\n' "$editor" "$lab_dir"
printf 'The initial admin password is in /etc/semaphore/initial-admin-password (root only).\n'
