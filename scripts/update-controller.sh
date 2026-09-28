#!/usr/bin/env bash
# Bring a controller made by either installer up to this copy of the guide.
# No arguments or --plan: show what would change. --apply: change it.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: sudo bash scripts/update-controller.sh [--plan | --apply] [--lab-dir DIR]
                                            [--replace-edited] [--project-id ID]

Brings a controller that install-controller.sh or install-controller-el9.sh set
up to the version of the guide in this copy, without reinstalling anything:
  - updates the guide's own files in the lab folder (playbooks/, ansible.cfg and
    scripts/summarize_xccdf.py) that only the guide changed, keeps the ones you
    changed, keeps every file you added, and commits the result in the folder's
    Git history;
  - creates the folder's content/ directory for SCAP files you supply;
  - adds the variable groups, template tabs and templates this release seeds
    that the Semaphore project lacks, and puts seeded templates that have no
    tab on theirs, after saving the templates as they were.
It does not change Semaphore, PostgreSQL, Ansible, the inventory, keys or other
template settings. It stops, changing nothing, when the lab folder has
uncommitted changes to guide files, staged changes, links where guide files
belong, or files that both you and this release changed.

  --lab-dir DIR       The lab folder (default: /opt/ansible-lab).
  --replace-edited    Replace guide files that both you and this release changed.
  --project-id ID     The seeded project's ID, if several projects share its name.

The default is a read-only plan. If the installer's admin password was changed
in the UI, it asks for a Semaphore administrator's login and password. Without a
terminal, export SEMAPHORE_API_TOKEN with an API token instead and run it with
sudo --preserve-env=SEMAPHORE_API_TOKEN.
USAGE
}

for argument in "$@"; do
  case "$argument" in
    --help|-h) usage; exit 0 ;;
  esac
done
for argument in "$@"; do
  case "$argument" in
    --plan|--apply|--replace-edited|--lab-dir|--project-id|--lab-dir=*|--project-id=*) ;;
    --*) usage; exit 2 ;;
  esac
done
[[ $(id -u) == 0 ]] || { echo 'Run it with sudo on the controller.' >&2; exit 1; }
command -v python3.12 >/dev/null || { echo 'python3.12 is missing; the installer put it there.' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3.12 "$script_dir/update-controller.py" "$@"
