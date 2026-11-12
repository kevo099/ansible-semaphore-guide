#!/usr/bin/env bash
# Bring the Ansible runtime and Semaphore's SSH settings of a controller that either
# installer made up to this copy of the guide. controller/update-controller.sh updates
# the lab folder and the Semaphore project; these two live outside both, so it leaves
# them alone and names this script when they are older.
# Usage: sudo bash controller/update-runtime.sh [--plan | --apply] [--force]
#
# No arguments or --plan: show what is older than this copy and change nothing.
# --apply changes only what the plan lists:
#   - /opt/ansible-venv: installs the versions requirements-controller.txt pins, in
#     place. A controller installed from v1.1.0 or v1.2.0 has ansible-core 2.20.8. The
#     list of what was installed is saved first; if the installation fails, those
#     versions are installed again. Packages you added yourself are kept.
#   - /etc/semaphore/config.json: adds SSH connection reuse to ANSIBLE_SSH_ARGS, which
#     controllers installed before v1.8.0 lack, so a job logs in to a host once
#     instead of once per task. The file as it was is saved first.
# Both saved files are root-only, under /root/ansible-lab-update/.
#
# Semaphore is stopped while these change and started again afterwards, usually within
# a minute, and the readiness check runs last. While a Semaphore task runs
# (ansible-playbook as the semaphore account) it stops and changes nothing, because
# stopping Semaphore stops that task; --force goes ahead anyway. It does not change
# Semaphore itself, PostgreSQL, the lab folder, the inventory or keys. Running it
# again changes nothing.
set -euo pipefail
umask 077
# No LC_ALL=C here, unlike the scripts that read a machine's output: Ansible refuses to
# start without a UTF-8 locale, and the readiness check at the end runs it.

# Print the comment block at the top of this file.
usage() { sed -n '2,/^[^#]/{/^#/p}' "$0"; }

mode=--plan force='' hint='' selected=''
for argument in "$@"; do
  case "$argument" in
    --help|-h) usage; exit 0 ;;
    --plan|--apply)
      [[ -z $selected || $selected == "$argument" ]] || { usage; exit 2; }
      selected=$argument; mode=$argument ;;
    --force) force=1 ;;
    # For update-controller.sh: a few lines when something is older, otherwise nothing.
    --hint) hint=1 ;;
    *) usage; exit 2 ;;
  esac
done
[[ $(id -u) == 0 ]] || { echo 'Run it with sudo on the controller.' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
requirements=$repo_dir/requirements-controller.txt
pip=/opt/ansible-venv/bin/pip
config=/etc/semaphore/config.json
saved=/root/ansible-lab-update
reuse='-o ControlMaster=auto -o ControlPersist=60s'

if [[ ! -x $pip || ! -f $config ]]; then
  [[ -z $hint ]] || exit 0
  echo "No /opt/ansible-venv or $config here: this controller was not made by the guide's installer."
  exit 1
fi
[[ -f $requirements ]] || { echo "Missing $requirements; run this from a complete copy of the guide."; exit 1; }

# One line per pinned package whose installed version differs: NAME INSTALLED PINNED, with
# "missing" for one that is absent. Lines that start with "+" name packages the pins do
# not cover, which stay as they are.
compare_runtime() {
  "$pip" --disable-pip-version-check freeze 2>/dev/null | python3 -I -c '
import re, sys

def key(name):
    return re.sub(r"[-_.]+", "-", name).lower()

pins = {}
for line in open(sys.argv[1]):
    line = line.split("#")[0].strip()
    if not line:
        continue
    match = re.fullmatch(r"([A-Za-z0-9._-]+)==([A-Za-z0-9.!+_-]+)", line)
    if not match:
        sys.exit("requirements-controller.txt has a line this script cannot read: " + line)
    pins[key(match[1])] = match.groups()
installed, other = {}, []
for line in sys.stdin:
    line = line.strip()
    match = re.fullmatch(r"([A-Za-z0-9._-]+)==(\S+)", line)
    if match:
        installed[key(match[1])] = match[2]
    elif line:
        other.append(line.split()[0])
for name, (shown, version) in pins.items():
    have = installed.get(name)
    if have != version:
        print(shown, have or "missing", version)
for name in sorted(set(installed) - set(pins)) + other:
    print("+", name)
' "$requirements"
}

# "set" when ANSIBLE_SSH_ARGS already reuses connections, "missing" when it can be added,
# "absent" when config.json has no ANSIBLE_SSH_ARGS of the installer's form to add it to.
ssh_reuse_state() {
  python3 -I -c '
import json, sys
try:
    arguments = json.load(open(sys.argv[1]))["env_vars"]["ANSIBLE_SSH_ARGS"]
except (KeyError, TypeError, ValueError):
    arguments = None
if not isinstance(arguments, str) or "UserKnownHostsFile=" not in arguments:
    print("absent")
elif "ControlMaster" in arguments or "ControlPersist" in arguments:
    print("set")
else:
    print("missing")
' "$config"
}

compared=$(compare_runtime) || { echo "Could not compare /opt/ansible-venv with $requirements."; exit 1; }
changes=$(printf '%s\n' "$compared" | grep -v -e '^+' -e '^$' || true)
added=$(printf '%s\n' "$compared" | sed -n 's/^+ //p')
ssh_reuse=$(ssh_reuse_state)
core_now=$(printf '%s\n' "$changes" | awk '$1 == "ansible-core" {print $2 " installed, " $3 " pinned"}')

if [[ -n $hint ]]; then
  [[ -n $changes || $ssh_reuse == missing ]] || exit 0
  echo 'Also older than this copy of the guide, and left alone by update-controller.sh:'
  [[ -z $changes ]] || echo "  Ansible runtime /opt/ansible-venv: ${core_now:-$(printf '%s\n' "$changes" | wc -l) pinned package(s) differ}"
  [[ $ssh_reuse != missing ]] || echo '  SSH connection reuse for Semaphore jobs: not set'
  echo 'To see and apply those: sudo bash controller/update-runtime.sh'
  exit 0
fi

echo "This copy of the guide -> the controller's Ansible runtime and Semaphore's SSH settings"
if [[ -n $changes ]]; then
  echo "  Ansible runtime /opt/ansible-venv, packages to install at the pinned version: $(printf '%s\n' "$changes" | wc -l)"
  printf '%s\n' "$changes" | awk '{print "    " $1 " " $2 " -> " $3}'
else
  echo '  Ansible runtime /opt/ansible-venv: every pinned package is at its pinned version.'
fi
if [[ -n $added ]]; then
  echo "  Packages you added, kept as they are: $(printf '%s\n' "$added" | wc -l)"
  printf '%s\n' "$added" | sed 's/^/    /'
fi
case $ssh_reuse in
  set) echo '  SSH connection reuse for Semaphore jobs: already set.' ;;
  missing) echo "  SSH connection reuse for Semaphore jobs: to add to ANSIBLE_SSH_ARGS in $config." ;;
  absent) echo "  SSH connection reuse for Semaphore jobs: $config has no ANSIBLE_SSH_ARGS of the installer's form; left alone." ;;
esac
if [[ -z $changes && $ssh_reuse != missing ]]; then
  echo 'Nothing to do: both match this copy of the guide.'
  exit 0
fi
if [[ $mode == --plan ]]; then
  echo 'Plan only. Run again with --apply to make these changes; Semaphore stops while they are made.'
  exit 0
fi

# Stopping Semaphore stops every task it runs, which can leave a host half changed.
if [[ -z $force ]] && pgrep -u semaphore -f ansible-playbook >/dev/null; then
  echo 'A Semaphore task is running (ansible-playbook as the semaphore account). These changes'
  echo 'need Semaphore stopped, and that would stop the task. Nothing was changed: run this'
  echo 'again once the task has finished, or add --force to go ahead anyway.'
  exit 1
fi

install -d -m 0700 "$saved"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
was_active=no
if systemctl is-active --quiet semaphore; then was_active=yes; fi
start_again() {
  if [[ $was_active == yes ]]; then systemctl start semaphore || echo 'Semaphore did not start; see sudo journalctl -u semaphore.'; fi
}
systemctl stop semaphore

if [[ -n $changes ]]; then
  before=$saved/ansible-venv-before-$stamp.txt
  "$pip" --disable-pip-version-check freeze > "$before"
  echo "Installed packages as they were: $before"
  # The service reads the environment as another account: files must not be root-only.
  if ! (umask 022 && "$pip" install --disable-pip-version-check --requirement "$requirements"); then
    echo 'Installing the pinned versions failed; installing the earlier versions again.'
    if (umask 022 && "$pip" install --disable-pip-version-check --requirement "$before"); then
      echo 'The earlier versions are back. Nothing else was changed.'
    else
      echo "Could not put the earlier versions back. Once the cause is fixed, run:"
      echo "  sudo $pip install --requirement $before"
    fi
    chmod -R go+rX /opt/ansible-venv
    start_again
    exit 1
  fi
  chmod -R go+rX /opt/ansible-venv
  left=$(compare_runtime | grep -v -e '^+' -e '^$' || true)
  if [[ -n $left ]]; then
    echo 'pip finished, but these packages are still not at their pinned version:'
    printf '%s\n' "$left" | awk '{print "  " $1 " " $2 " (pinned " $3 ")"}'
    echo "The earlier list is in $before."
    start_again
    exit 1
  fi
  echo "Ansible runtime updated: $(printf '%s\n' "$changes" | wc -l) package(s) are now at their pinned version."
fi

if [[ $ssh_reuse == missing ]]; then
  before=$saved/semaphore-config-before-$stamp.json
  install -m 0600 "$config" "$before"
  echo "Semaphore's configuration as it was (holds secrets, root-only): $before"
  python3 -I - "$config" "$reuse" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
config = json.loads(p.read_text())
config["env_vars"]["ANSIBLE_SSH_ARGS"] = sys.argv[2] + " " + config["env_vars"]["ANSIBLE_SSH_ARGS"]
p.write_text(json.dumps(config, indent=2) + "\n")
PY
  chown root:semaphore "$config"
  chmod 0640 "$config"
  echo 'SSH connection reuse added to ANSIBLE_SSH_ARGS.'
fi

start_again
if [[ $was_active == no ]]; then
  echo 'Semaphore was stopped before this ran and is still stopped; start it with sudo systemctl start semaphore.'
  exit 0
fi
for _ in {1..30}; do
  if curl -fs -o /dev/null http://127.0.0.1:3000/api/ping; then break; fi
  sleep 1
done
if readiness=$(python3.12 "$script_dir/check-controller.py"); then
  echo 'Updated. The readiness check passed.'
else
  echo 'Updated, but the readiness check does not pass:'
  printf '%s\n' "$readiness" | python3 -I -c '
import json, sys
try:
    checks = json.load(sys.stdin)["checks"]
except (KeyError, TypeError, ValueError):
    checks = {}
for name, passed in checks.items():
    if not passed:
        print("  " + name)'
  echo 'For all of it: sudo python3.12 controller/check-controller.py'
  exit 1
fi
