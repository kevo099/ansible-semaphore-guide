#!/usr/bin/env bash
# Bring a controller made by either installer up to this copy of the guide.
# No arguments or --plan: show what would change. --apply: change it.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: sudo bash scripts/update-controller.sh [--plan | --apply] [--lab-dir DIR]
                                            [--replace-edited] [--project-id ID]
                                            [--remove-replaced]

Brings a controller that install-controller.sh or install-controller-el9.sh set
up to the version of the guide in this copy, without reinstalling anything:
  - updates the guide's own files in the lab folder (playbooks/, ansible.cfg and
    scripts/summarize_xccdf.py) that only the guide changed, keeps the ones you
    changed, keeps every file you added, and commits the result in the folder's
    Git history;
  - creates the folder's content/ directory, with one folder per STIG system
    and version, for SCAP files you supply;
  - adds the variable groups, template tabs and templates this release seeds
    that the Semaphore project lacks, and puts seeded templates that have no
    tab on theirs, after saving the templates as they were;
  - lists the seeded templates, tab and variable group this release replaces,
    and keeps them unless you pass --remove-replaced.
It does not change Semaphore, PostgreSQL, Ansible, the inventory, keys or other
template settings. It stops, changing nothing, when the lab folder has
uncommitted changes to guide files, staged changes, links where guide files
belong, or files that both you and this release changed. If writing the files
fails part way, it puts back the ones it wrote.

  --lab-dir DIR       The lab folder (default: /opt/ansible-lab).
  --replace-edited    Replace guide files that both you and this release changed.
  --project-id ID     The seeded project's ID, if several projects share its name.
  --remove-replaced   After the update, delete the replaced seeded objects, with
                      the old templates' task history; a backup of their
                      settings is saved under /root/ansible-lab-update/ first.
                      A replaced template that a schedule or integration runs
                      is kept until you move those to its per-system template.

The default is a read-only plan; it exits with status 1 when it lists problems
that would stop --apply. If the installer's admin password was changed in the
UI, it asks for a Semaphore administrator's login and password. Without a
terminal, or for a login with a second factor, export SEMAPHORE_API_TOKEN with
the API token of a Semaphore administrator, or of the project's owner or a
manager, and run it with sudo --preserve-env=SEMAPHORE_API_TOKEN.
USAGE
}

for argument in "$@"; do
  case "$argument" in
    --help|-h) usage; exit 0 ;;
  esac
done
for argument in "$@"; do
  case "$argument" in
    --plan|--apply|--replace-edited|--remove-replaced|--lab-dir|--project-id|--lab-dir=*|--project-id=*) ;;
    --*) usage; exit 2 ;;
  esac
done
[[ $(id -u) == 0 ]] || { echo 'Run it with sudo on the controller.' >&2; exit 1; }
command -v python3.12 >/dev/null || { echo 'python3.12 is missing; the installer put it there.' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3.12 "$script_dir/update-controller.py" "$@"
