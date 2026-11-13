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
  expose_address=
  fapolicyd_ready=no
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --plan|--apply)
        [[ -z "$selected_mode" || "$selected_mode" == "$1" ]] || { usage; exit 2; }
        selected_mode="$1"; mode="$1" ;;
      --editor) [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { usage; exit 2; }; editor="$2"; shift ;;
      --lab-dir) [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { usage; exit 2; }; lab_dir="$2"; shift ;;
      --expose) [[ $# -ge 2 && ( "$2" == https || "$2" == http ) ]] || { usage; exit 2; }; expose="$2"; shift ;;
      # expose-semaphore.sh checks the value; it names the certificate and the printed URL.
      --address) [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { usage; exit 2; }; expose_address="$2"; shift ;;
      --fapolicyd-ready) fapolicyd_ready=yes ;;
      *) usage; exit 2 ;;
    esac
    shift
  done
  [[ -z "$expose_address" || -n "$expose" ]] || { echo 'Pass --address together with --expose.'; usage; exit 2; }
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

# The four fapolicyd rules a controller of this guide needs, with this run's paths.
controller_fapolicyd_rules() {
  printf '%s\n' \
    'allow perm=any all : path=/usr/local/bin/semaphore' \
    'allow perm=any all : dir=/opt/ansible-venv/' \
    "allow perm=open all : dir=$lab_dir/ ftype=%languages" \
    "allow perm=open all : dir=$repo_dir/ ftype=%languages"
}

# The DISA STIG turns on fapolicyd, which denies programs that no package installed:
# here Semaphore's binary and the Ansible runtime. It also keeps an administrator and
# Git from reading the guide's scripts. Without rules for them this installation would
# stop halfway, at Semaphore's first run, and the installer cannot be run a second time.
# So it stops here, before it changes anything, and prints the rules to add.
# --fapolicyd-ready skips the check for a site that allowed the same paths another way.
controller_check_fapolicyd() {
  [[ "$fapolicyd_ready" == no ]] || return 0
  command -v fapolicyd-cli >/dev/null 2>&1 || return 0
  systemctl is-active --quiet fapolicyd || return 0
  # With permissive = 1 fapolicyd only logs what it would deny.
  if grep -Eq '^[[:space:]]*permissive[[:space:]]*=[[:space:]]*1' \
       "${fapolicyd_conf:-/etc/fapolicyd/fapolicyd.conf}" 2>/dev/null; then
    return 0
  fi
  local loaded rule library ours missing=0
  loaded=$(fapolicyd-cli --list 2>/dev/null) || loaded=
  while IFS= read -r rule; do
    grep -qF -- "$rule" <<<"$loaded" || missing=1
  done < <(controller_fapolicyd_rules)
  # The runtime holds shared libraries, so its rule has to come before fapolicyd's own
  # rule that denies the ones no package installed.
  # grep finds nothing where a rule is missing; that must not end the installer here.
  library=$(grep -n 'deny.*ftype=application/x-sharedlib' <<<"$loaded" | head -n 1 | cut -d: -f1) || true
  ours=$(grep -nF -- 'dir=/opt/ansible-venv/' <<<"$loaded" | head -n 1 | cut -d: -f1) || true
  if (( missing == 0 )) && [[ -z "$library" || ( -n "$ours" && "$ours" -lt "$library" ) ]]; then
    return 0
  fi
  cat <<MESSAGE
fapolicyd is active on this machine, as on a system hardened to the DISA STIG. It
denies programs that no package installed, which here are Semaphore's binary and
the Ansible runtime, and it keeps your account and Git from reading the guide's
scripts. This installation would stop halfway and could not be run again, so
nothing was changed.

As root, put these four lines in
/etc/fapolicyd/rules.d/35-ansible-semaphore-guide.rules. The number matters: they
have to come before fapolicyd's own rules for shared libraries.

$(controller_fapolicyd_rules)

Then load them and run this installer again:

  sudo fagenrules --load

docs/09-security-benchmarks.md, "Harden the controller itself", explains each
line. If your site allowed the same paths another way, pass --fapolicyd-ready.
MESSAGE
  exit 1
}

controller_check_sources() {
  for path in controller_config.py create-database.py create-admin.py check-controller.py seed-semaphore.py add-target.sh expose-semaphore.sh; do
    [[ -f "$script_dir/$path" ]] || { echo "Missing helper: $path"; exit 1; }
  done
  # The lab folder gets its own copy of this one, at the same path the playbooks call.
  [[ -f "$repo_dir/scripts/summarize_xccdf.py" ]] || { echo 'Missing helper: scripts/summarize_xccdf.py'; exit 1; }
  [[ -f "$script_dir/templates/$1" ]] || { echo 'Missing service template.'; exit 1; }
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

controller_apt_update() {
  # Ubuntu. apt-get waits for the dpkg lock only when given DPkg::Lock::Timeout, and
  # apt-get update takes the package lists' lock, which that option does not cover.
  # apt-daily can hold it for a while after boot, so retry for about five minutes.
  local attempt
  for attempt in {1..30}; do
    if apt-get update; then return; fi
    if (( attempt < 30 )); then
      echo 'apt-get update failed; another apt process may hold its lock. Retrying in 10 seconds.'
      sleep 10
    fi
  done
  echo 'apt-get update failed 30 times. Nothing was installed; fix the cause above and rerun --apply.'
  exit 1
}

controller_apt_install_postgresql() {
  # Ubuntu installs PostgreSQL after the runtime, because the package creates state the
  # preflight refuses. If it fails before creating any, remove the new runtime as well,
  # so that the operator can fix the cause and rerun the fresh installer.
  if apt-get -o DPkg::Lock::Timeout=600 install -y postgresql-16; then return; fi
  if [[ -e /etc/postgresql || -e /var/lib/postgresql ]]; then
    echo 'Installing PostgreSQL 16 failed after it created /etc/postgresql or /var/lib/postgresql,'
    echo 'so this installer refuses to run again on this VM. See docs/11-troubleshooting.md'
    echo '(Installer interrupted or failed).'
  else
    rm -rf /opt/ansible-venv
    echo 'Installing PostgreSQL 16 failed; removed the new /opt/ansible-venv. Fix the cause above and rerun --apply.'
  fi
  exit 1
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
  install -o root -g root -m 0644 "$script_dir/templates/$1" /etc/systemd/system/semaphore.service
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
  # A copy of the public key in the editor's home, where the onboarding steps look
  # for it. The editor writes it, so a link planted there cannot redirect root.
  editor_home=$(getent passwd "$editor" | cut -d: -f6) || editor_home=
  key_copy=
  # shellcheck disable=SC2016  # expanded by the editor's own shell
  if [[ -d "$editor_home" ]] && runuser -u "$editor" -- /bin/sh -c 'umask 022 && cat > "$1"' _ "$editor_home/svc_ansible.pub" \
       < /etc/semaphore/svc_ansible.pub; then
    key_copy=$editor_home/svc_ansible.pub
  fi

  # 11. Local lab folder owned by the editor, readable by the service
  (umask 022; mkdir -p -- "$(dirname -- "$lab_dir")")
  install -d -o "$editor" -g semaphore -m 2750 "$lab_dir" "$lab_dir/inventories" "$lab_dir/content"
  # One folder per STIG system and version for SCAP files you supply, as in playbooks/stig/
  local system
  for system in rhel/9 almalinux/9 rocky/9 ubuntu/24.04; do
    install -d -o "$editor" -g semaphore -m 2750 "$lab_dir/content/${system%/*}" "$lab_dir/content/$system"
  done
  cp -r "$repo_dir/playbooks" "$lab_dir/playbooks"
  install -o "$editor" -g semaphore -m 0640 "$repo_dir/ansible.cfg" "$lab_dir/ansible.cfg"
  install -d -o "$editor" -g semaphore -m 2750 "$lab_dir/scripts"
  install -o "$editor" -g semaphore -m 0640 "$repo_dir/scripts/summarize_xccdf.py" "$lab_dir/scripts/summarize_xccdf.py"
  cat > "$lab_dir/inventories/lab.ini" <<'INVENTORY'
# Local lab inventory read by Semaphore at every run. Add one line per target
# under the matching group, for example:
#   lab-ubuntu ansible_host=ubuntu.example.test
# Use controller/add-target.sh to add a host together with its verified host key.
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
  # No hook samples from Git's templates: the folder needs none, and where fapolicyd is
  # active an account other than root may not read one of them, which stops git init.
  runuser -u "$editor" -- git -C "$lab_dir" init -q -b main --template=
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
    echo 'then seed Semaphore (and, if you chose --expose, run expose-semaphore.sh with that mode):'
    echo "  sudo python3.12 $script_dir/seed-semaphore.py --lab-dir $lab_dir \\"
    echo '    --key-file /etc/semaphore/svc_ansible --known-hosts /etc/semaphore/known_hosts'
    exit 1
  fi

  # 12. Seed Semaphore through its API
  python3.12 "$script_dir/seed-semaphore.py" --lab-dir "$lab_dir" \
    --key-file /etc/semaphore/svc_ansible --known-hosts /etc/semaphore/known_hosts
}

controller_finish() {
  # 13. Optional network exposure. The controller is complete without it, so when this
  #     step fails, only the exposure script needs to run again, not the installer.
  local expose_command=() exposure_failed=
  if [[ -n "$expose" ]]; then
    expose_command=(bash "$script_dir/expose-semaphore.sh" --mode "$expose")
    [[ -z "$expose_address" ]] || expose_command+=(--address "$expose_address")
    if ! { "${expose_command[@]}" && python3.12 "$script_dir/check-controller.py"; }; then
      exposure_failed=1
    fi
  fi

  printf '\nController installed and seeded. Next: prepare each target and add it with its verified\n'
  printf 'host key. For a machine that already exists, as your administrator in this folder:\n'
  printf '  bash controller/onboard-target.sh ADMIN@ADDRESS%s\n' "$([[ $lab_dir == /opt/ansible-lab ]] || printf ' --lab-dir %q' "$lab_dir")"
  printf 'README.md lists the other ways, and cloud-init for new VMs.\n'
  printf 'Automation public key: /etc/semaphore/svc_ansible.pub%s\n' "${key_copy:+ (a copy is in $key_copy)}"
  printf 'Local lab folder (edit as %s): %s\n' "$editor" "$lab_dir"
  printf 'The initial admin password is in /etc/semaphore/initial-admin-password (root only).\n'
  if [[ -n "$exposure_failed" ]]; then
    printf '\nOnly the --expose %s step failed. Do not run the installer again; fix the cause above, then run:\n  sudo' "$expose"
    printf ' %q' "${expose_command[@]}"
    printf '\n  sudo python3.12 %q\n' "$script_dir/check-controller.py"
    exit 1
  fi
}
