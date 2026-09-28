#!/usr/bin/env bash
# Shared bootstrap steps for the Ubuntu 24.04 and Enterprise Linux 9 installers.
# Sourced after each installer sets script_dir/repo_dir and controller_family.
# Defining these functions has no side effects; only --apply calls mutating steps.
# Those three globals are supplied by the installer sourcing this file.
# shellcheck disable=SC2154

# mode is checked by the caller before any preflight or install step.
# shellcheck disable=SC2034
controller_parse_args() {
  local selected_mode=
  mode=--plan
  editor="${SUDO_USER:-}"
  lab_dir=/opt/ansible-lab
  expose=
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --plan|--apply)
        [[ -z "$selected_mode" || "$selected_mode" == "$1" ]] || { usage; exit 2; }
        selected_mode="$1"; mode="$1" ;;
      --editor) [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { usage; exit 2; }; editor="$2"; shift ;;
      --lab-dir) [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { usage; exit 2; }; lab_dir="$2"; shift ;;
      --expose) [[ $# -ge 2 && ( "$2" == https || "$2" == http ) ]] || { usage; exit 2; }; expose="$2"; shift ;;
      *) usage; exit 2 ;;
    esac
    shift
  done
}

controller_validate_lab() {
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
}

controller_require_fresh_state() {
  for path in /etc/semaphore /opt/ansible-venv /usr/local/bin/semaphore \
              /var/lib/semaphore /etc/systemd/system/semaphore.service "$lab_dir" "$@"; do
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
}

controller_check_sources() {
  for path in controller_config.py create-database.py create-admin.py check-controller.py seed-semaphore.py add-target.sh expose-semaphore.sh summarize_xccdf.py; do
    [[ -f "$script_dir/$path" ]] || { echo "Missing helper: $path"; exit 1; }
  done
  [[ -f "$repo_dir/templates/$1" ]] || { echo 'Missing service template.'; exit 1; }
  [[ -d "$repo_dir/playbooks" && -f "$repo_dir/ansible.cfg" ]] || { echo 'Missing guide playbooks.'; exit 1; }
  [[ -f "$repo_dir/requirements-controller.txt" ]] || { echo 'Missing requirements-controller.txt.'; exit 1; }
}

controller_download() {
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
}

controller_install_runtime() {
  # Preflight proved the directory absent; remove only this new runtime if pip
  # fails so the operator can fix the cause and rerun the fresh installer.
  if ! { python3.12 -m venv /opt/ansible-venv &&
         /opt/ansible-venv/bin/pip install --disable-pip-version-check \
           --requirement "$repo_dir/requirements-controller.txt"; }; then
    rm -rf /opt/ansible-venv
    echo 'Creating /opt/ansible-venv failed; removed the new directory. Fix the cause and rerun --apply.'
    exit 1
  fi
  chmod -R go+rX /opt/ansible-venv
}

controller_configure_account() {
  useradd --system --create-home --home-dir /var/lib/semaphore --shell /usr/sbin/nologin semaphore
  install -d -o root -g semaphore -m 0750 /etc/semaphore
  install -d -o semaphore -g semaphore -m 0700 /var/lib/semaphore /var/lib/semaphore/tmp
  python3.12 "$script_dir/controller_config.py" --directory /etc/semaphore
  chown root:semaphore /etc/semaphore/config.json
  chmod 0640 /etc/semaphore/config.json
  install -o root -g semaphore -m 0640 /dev/null /etc/semaphore/known_hosts
  # Let Git quote unusual path characters instead of interpolating its config.
  git config --file /etc/semaphore/gitconfig --add safe.directory "$lab_dir"
  chown root:semaphore /etc/semaphore/gitconfig
  chmod 0640 /etc/semaphore/gitconfig
}

controller_start() {
  cd "$cache" || return
  install -m 0755 semaphore /usr/local/bin/semaphore
  if [[ "$controller_family" == el ]]; then restorecon -F /usr/local/bin/semaphore; fi
  runuser -u semaphore -- /usr/local/bin/semaphore migrate --config /etc/semaphore/config.json
  python3.12 "$script_dir/create-admin.py"
  install -o root -g root -m 0644 "$repo_dir/templates/$1" /etc/systemd/system/semaphore.service
  systemctl daemon-reload
  systemctl enable --now semaphore

  for _ in {1..30}; do
    if curl -fs -o /dev/null http://127.0.0.1:3000/api/ping; then break; fi
    sleep 1
  done
  python3.12 "$script_dir/check-controller.py"
}

controller_seed_lab() {
  # 10. Automation key pair. Unencrypted by explicit choice for an unattended lab;
  #     the private key never leaves root-only storage except into the Key Store.
  ssh-keygen -q -t rsa -b 4096 -N '' -C ansible-practice -f /etc/semaphore/svc_ansible
  chmod 0600 /etc/semaphore/svc_ansible
  chmod 0644 /etc/semaphore/svc_ansible.pub

  # 11. Local lab folder owned by the editor, readable by the service
  (umask 022; mkdir -p -- "$(dirname -- "$lab_dir")")
  install -d -o "$editor" -g semaphore -m 2750 "$lab_dir" "$lab_dir/inventories" "$lab_dir/content"
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
  if [[ "$controller_family" == el ]]; then restorecon -RF "$lab_dir"; fi
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
}

controller_finish() {
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
}
