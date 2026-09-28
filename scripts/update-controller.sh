#!/usr/bin/env bash
# Bring a controller made by either installer up to this copy of the guide.
# No arguments or --plan: show what would change. --apply: change it.
set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
Usage: sudo bash scripts/update-controller.sh [--plan | --apply] [--lab-dir DIR]

Brings a controller that install-controller.sh or install-controller-el9.sh set
up to the version of the guide in this copy, without reinstalling anything:
  - replaces the guide's own files in the lab folder (playbooks/, ansible.cfg and
    scripts/summarize_xccdf.py) where they differ, keeps every file you added,
    and records the change as one commit in the folder's Git history;
  - creates the folder's content/ directory for SCAP files you supply;
  - adds the variable groups, template tabs and templates this release seeds
    that the Semaphore project lacks, and puts seeded templates that have no
    tab on theirs.
It does not change Semaphore, PostgreSQL, Ansible, the inventory, keys or any
other existing template. It refuses to overwrite a guide file you edited and
did not commit; commit or discard that edit first.

  --lab-dir DIR   The lab folder (default: /opt/ansible-lab).

The default is a read-only plan. If the installer's admin password no longer
logs in, export SEMAPHORE_API_TOKEN with an API token and run it with
sudo --preserve-env=SEMAPHORE_API_TOKEN.
USAGE
}

mode=--plan
lab_dir=/opt/ansible-lab
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --plan|--apply) mode="$1" ;;
    --lab-dir) [[ $# -ge 2 && -n "$2" ]] || { usage; exit 2; }; lab_dir="$2"; shift ;;
    *) usage; exit 2 ;;
  esac
  shift
done

fail() { echo "$*" >&2; exit 1; }
[[ $(id -u) == 0 ]] || fail 'Run it with sudo on the controller; it reads Semaphore settings only root can read.'
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
[[ -f /etc/semaphore/.practice-project-seeded ]] ||
  fail 'This controller was not set up by an installer that seeds Semaphore; there is nothing to update.'
[[ "$lab_dir" == /* && -d "$lab_dir/.git" ]] || fail "No lab folder with Git history at $lab_dir; pass --lab-dir."
lab_dir=$(realpath -- "$lab_dir")
command -v python3.12 >/dev/null || fail 'python3.12 is missing; the installer put it there.'
systemctl is-active --quiet semaphore || fail 'semaphore.service is not running; start it first.'
editor=$(stat -c %U -- "$lab_dir")
[[ "$editor" != root ]] || fail "$lab_dir belongs to root; the installer gives it to an administrator."
version=$(git -c safe.directory="$repo_dir" -C "$repo_dir" describe --tags --always 2>/dev/null || echo 'this copy')

as_editor() { runuser -u "$editor" -- "$@"; }

# The files the installers copy into the lab folder.
mapfile -t guide_files < <(cd -- "$repo_dir" &&
  { find playbooks -type f; printf '%s\n' ansible.cfg scripts/summarize_xccdf.py; } | LC_ALL=C sort)
added=() replaced=() same=0
for file in "${guide_files[@]}"; do
  if [[ ! -e "$lab_dir/$file" ]]; then
    added+=("$file")
  elif ! cmp -s -- "$repo_dir/$file" "$lab_dir/$file"; then
    replaced+=("$file")
  else
    same=$((same + 1))
  fi
done
mapfile -t yours < <(cd -- "$lab_dir" && find playbooks -type f | LC_ALL=C sort |
  comm -23 - <(printf '%s\n' "${guide_files[@]}"))
pending=
if [[ ${#replaced[@]} -gt 0 ]]; then
  pending=$(as_editor git -C "$lab_dir" status --porcelain -- "${replaced[@]}")
fi

list() { local item; for item in "$@"; do printf '    %s\n' "$item"; done; }
printf 'Guide %s -> lab folder %s (files owned by %s)\n' "$version" "$lab_dir" "$editor"
printf '  Files to add: %s\n' "${#added[@]}"; list "${added[@]}"
printf '  Files to replace: %s\n' "${#replaced[@]}"; list "${replaced[@]}"
printf '  Guide files already current: %s\n' "$same"
printf '  Your own files in playbooks/, kept: %s\n' "${#yours[@]}"; list "${yours[@]}"
[[ -d "$lab_dir/content" ]] || printf '  content/ will be created for SCAP files you supply\n'
if [[ -n "$pending" ]]; then
  printf '  Uncommitted edits to files it would replace:\n%s\n' "$pending"
fi

if [[ "$mode" == --plan ]]; then
  printf 'Semaphore project:\n'
  python3.12 "$script_dir/seed-semaphore.py" --update --plan --lab-dir "$lab_dir"
  printf 'Plan only. Run again with --apply to make these changes.\n'
  exit 0
fi

[[ -z "$pending" ]] ||
  fail "Refusing to overwrite uncommitted edits in $lab_dir. Commit them (git add and git commit) or discard them (git restore), then run again."

# The editor writes each file, so it keeps the folder's owner, and the folder's
# setgid bit gives it the semaphore group. Root reads the source and passes it in.
for file in "${added[@]}" "${replaced[@]}"; do
  # shellcheck disable=SC2016  # expanded by the editor's own shell
  as_editor /bin/bash -c '
    set -euo pipefail
    umask 027
    dir=$(dirname -- "$1")
    [[ -d "$dir" ]] || { mkdir -p -- "$dir"; chmod 2750 -- "$dir"; }
    cat > "$1.update-tmp"
    chmod 0640 -- "$1.update-tmp"
    mv -f -- "$1.update-tmp" "$1"' _ "$lab_dir/$file" < "$repo_dir/$file"
done
as_editor install -d -m 2750 "$lab_dir/content"
if command -v selinuxenabled >/dev/null && selinuxenabled; then restorecon -RF "$lab_dir"; fi
for file in "${added[@]}" "${replaced[@]}"; do
  runuser -u semaphore -- test -r "$lab_dir/$file" || fail "The semaphore account cannot read $lab_dir/$file."
done

if [[ ${#added[@]} -gt 0 || ${#replaced[@]} -gt 0 ]]; then
  identity=()
  [[ -n "$(as_editor git -C "$lab_dir" config user.name || true)" ]] ||
    identity=(-c user.name=ansible-practice -c user.email=ansible-practice@example.test)
  as_editor git -C "$lab_dir" add -- "${added[@]}" "${replaced[@]}"
  as_editor git -C "$lab_dir" "${identity[@]}" commit -q -m "Update the guide's files to $version"
  printf 'Committed the file changes in %s; git log shows them, and git revert undoes them.\n' "$lab_dir"
fi

printf 'Semaphore project:\n'
python3.12 "$script_dir/seed-semaphore.py" --update --lab-dir "$lab_dir"
python3.12 "$script_dir/check-controller.py" >/dev/null ||
  fail 'The readiness check failed after the update; run sudo python3.12 scripts/check-controller.py to see why.'
printf 'Updated to %s. The readiness check passed.\n' "$version"
