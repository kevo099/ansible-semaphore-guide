#!/usr/bin/env bash
# Retire one managed target: remove its inventory line and the trusted host key of its
# address, the inverse of controller/add-target.sh.
# Usage: sudo bash controller/remove-target.sh --name NAME [--lab-dir /opt/ansible-lab] \
#            [--known-hosts /etc/semaphore/known_hosts] [--keep-key]
#
# NAME is the inventory name add-target.sh added, such as lab-alma. The script removes
# only a line of the form add-target.sh writes, NAME ansible_host=ADDRESS; it refuses a
# group's name, a name listed more than once and a line with other settings, which
# are for editing by hand. It keeps the inventory as it was beside it, as
# lab.ini.before-remove-NAME.TIME.bak, and removes every key line that known-hosts
# holds for ADDRESS, plain or hashed, unless --keep-key is given or another inventory
# host uses the same address. A line that names ADDRESS among other hosts, as a
# pattern or with a marker such as @revoked is never edited: the script refuses.
#
# Both files are replaced whole, with their owner, group and mode, so the service can
# still read known-hosts, and without the .old copy that ssh-keygen -R leaves. If a
# replacement fails, both files stay as they were. A name that is not in the inventory
# changes nothing, so running it again is safe. Runs on one lab folder take turns with
# each other and with add-target.sh, waiting up to two minutes.
#
# It changes only the controller: the machine keeps the svc_ansible account, its
# authorized keys, its sudo rule and its SSH drop-in.
set -euo pipefail
umask 077
# Match bytes: in a UTF-8 locale, [A-Za-z] also matches other alphabets' look-alike letters.
export LC_ALL=C

# Print the comment block at the top of this file.
usage() { sed -n '2,/^[^#]/{/^#/p}' "$0"; }
missing() { echo "$1 needs a value."; usage; exit 2; }

name='' lab_dir=/opt/ansible-lab known_hosts=/etc/semaphore/known_hosts keep_key=no
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) [[ $# -ge 2 ]] || missing "$1"; name="$2"; shift ;;
    --lab-dir) [[ $# -ge 2 ]] || missing "$1"; lab_dir="$2"; shift ;;
    --known-hosts) [[ $# -ge 2 ]] || missing "$1"; known_hosts="$2"; shift ;;
    --keep-key) keep_key=yes ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; exit 2 ;;
  esac
  shift
done
[[ -n "$name" ]] || { usage; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'Run with sudo: the service known-hosts file is root-owned.'; exit 1; }
# The name is matched against inventory fields and ends up in a file name: a plain token only.
[[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo 'Inventory name must be a plain hostname-like token.'; exit 1; }
inventory="$lab_dir/inventories/lab.ini"
# One run at a time per lab folder, shared with add-target.sh: the files are read,
# checked and replaced as one step.
{ exec 9<"$lab_dir/inventories"; } 2>/dev/null || { echo 'Missing inventory or known-hosts file.'; exit 1; }
flock -w 120 9 || { echo "Another add-target.sh or remove-target.sh run is changing $lab_dir; run this again when it has finished."; exit 1; }
[[ -f "$inventory" && -f "$known_hosts" ]] || { echo 'Missing inventory or known-hosts file.'; exit 1; }
# A replacement would turn a link into a file and leave its target as it was.
for file in "$inventory" "$known_hosts"; do
  [[ ! -L "$file" ]] || { echo "$file is a symbolic link; edit it by hand instead."; exit 1; }
done

# Read sections as Ansible does: [NAME], [NAME:vars] and [NAME:children] headers, with
# surrounding spaces allowed. A line under :children names a group, and one under :vars
# a variable; only lines under the other sections are hosts.
sections='
  match($0, /^[[:space:]]*\[[^]]+\]/) {
    header = substr($0, RSTART, RLENGTH); sub(/^[[:space:]]*\[/, "", header); sub(/\]$/, "", header)
    kind = header ~ /:vars$/ ? "vars" : header ~ /:children$/ ? "children" : "hosts"
    sub(/:.*/, "", header); headers[header] = 1
    next
  }
  $1 ~ /^[#;]/ {next}'
# Compare whole fields as text, as add-target.sh does: a dot in the name is not a wildcard.
found=$(awk -v n="$name" 'BEGIN {kind = "hosts"}'"$sections"'
    $1 == (n "") {if (kind == "children") group = 1; else if (kind == "hosts") lines = lines " " NR}
    END {print ((group || (n in headers) || n == "all" || n == "ungrouped") ? "group" : "host") lines}' "$inventory")
if [[ $found == group* ]]; then
  echo "$name is the name of an inventory group, not of a host; nothing changed."; exit 1
fi
read -r -a numbers <<< "${found#host}"
if [[ ${#numbers[@]} -eq 0 ]]; then
  echo "$name is not in $inventory; nothing changed."; exit 0
fi
if [[ ${#numbers[@]} -gt 1 ]]; then
  echo "$inventory lists $name on ${#numbers[@]} lines; remove it by hand instead."; exit 1
fi
number=${numbers[0]}
line=$(sed -n "${number}p" "$inventory")
read -r -a fields <<< "${line%$'\r'}"
address=${fields[1]:-}
address=${address#ansible_host=}
if [[ ${#fields[@]} -ne 2 || ${fields[1]} != ansible_host=* || ! $address =~ ^[A-Za-z0-9:][A-Za-z0-9.:-]*$ ]]; then
  echo "$inventory lists $name with other settings than add-target.sh writes ($name ansible_host=ADDRESS);"
  echo "remove it and its host key by hand instead."
  exit 1
fi

# Another host at the same address, such as one added by hand, still needs the key. A
# host without ansible_host is reached at its own name.
sharer=$(awk -v a="$address" -v skip="$number" 'BEGIN {kind = "hosts"}'"$sections"'
    kind != "hosts" || NR == skip || NF == 0 {next}
    {
      host = $1
      for (i = 2; i <= NF; i++) if ($i ~ /^ansible_host=/) host = substr($i, 14)
      if (host == (a "")) {print $1; exit}
    }' "$inventory")

# ssh-keygen -F finds plain and hashed entries for the address, and names their lines.
key_lines=()
if [[ $keep_key == no && -z $sharer ]]; then
  while read -r key_line; do
    entry=$(sed -n "${key_line}p" "$known_hosts")
    entry=${entry#"${entry%%[![:space:]]*}"}
    hosts=${entry%%[[:space:]]*}
    # Only a line for this address alone: its plain address, or a hashed entry, which
    # always stands for one host.
    if [[ $hosts != "$address" && $hosts != '|1|'* ]]; then
      echo "Line $key_line of $known_hosts names $address among other hosts, as a pattern or with a marker"
      echo "such as @revoked; edit that line by hand, or run this again with --keep-key. Nothing changed."
      exit 1
    fi
    key_lines+=("$key_line")
  done < <(ssh-keygen -F "$address" -f "$known_hosts" 2>/dev/null |
           awk '/^# Host .* found: line [0-9]/ {for (i = 1; i < NF; i++) if ($i == "line") {print $(i + 1); break}}')
fi

inventory_dir=$(dirname -- "$inventory")
known_dir=$(dirname -- "$known_hosts")
backup="$inventory.before-remove-$name.$(date +%Y%m%dT%H%M%S).bak"
saved_known_hosts="$known_dir/.$(basename -- "$known_hosts").remove-target.$$"
new_inventory='' new_known_hosts='' state=planned
# Runs on every exit. Until the inventory is replaced, it puts known-hosts back and
# drops the copy of the inventory, so a run that stops changes nothing.
finish() {
  local status=$?
  case $state in
    copied) rm -f -- "$backup" ;;
    linked) rm -f -- "$backup" "$saved_known_hosts" ;;
    key-removed)
      if mv -f -- "$saved_known_hosts" "$known_hosts"; then
        rm -f -- "$backup"
        echo "Put $known_hosts back as it was; nothing changed."
      else
        echo "Could not put $known_hosts back; its previous version is $saved_known_hosts. Put it back with:"
        echo "  sudo mv -f $saved_known_hosts $known_hosts"
        echo "$inventory was not changed."
      fi ;;
  esac
  rm -f -- ${new_inventory:+"$new_inventory"} ${new_known_hosts:+"$new_known_hosts"}
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# A replacement keeps the owner, group, mode and SELinux label of the file it replaces.
same_attributes() {
  chown --reference="$1" -- "$2" || return 1
  chmod --reference="$1" -- "$2" || return 1
  if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then
    chcon --reference="$1" -- "$2" || return 1
  fi
}
new_inventory=$(mktemp "$inventory_dir/.$(basename -- "$inventory").XXXXXX") ||
  { echo "Could not write in $inventory_dir; nothing changed."; exit 1; }
awk -v skip="$number" 'NR != skip' "$inventory" > "$new_inventory"
same_attributes "$inventory" "$new_inventory" ||
  { echo "Could not give the new inventory the owner and mode of $inventory; nothing changed."; exit 1; }
if [[ -n $(awk -v n="$name" '$1 == (n "")' "$new_inventory") ]]; then
  echo "The new inventory still lists $name; nothing changed."; exit 1
fi
if [[ ${#key_lines[@]} -gt 0 ]]; then
  # What the removed lines trusted, shown once they are gone.
  removed_keys=$(for key_line in "${key_lines[@]}"; do sed -n "${key_line}p" "$known_hosts"; done |
                 ssh-keygen -lf - 2>/dev/null | awk '{print "  " $2 " " $NF}') || removed_keys=''
  new_known_hosts=$(mktemp "$known_dir/.$(basename -- "$known_hosts").XXXXXX") ||
    { echo "Could not write in $known_dir; nothing changed."; exit 1; }
  awk -v drop=" ${key_lines[*]} " 'index(drop, " " NR " ") == 0' "$known_hosts" > "$new_known_hosts"
  same_attributes "$known_hosts" "$new_known_hosts" ||
    { echo "Could not give the new known-hosts file the owner and mode of $known_hosts; nothing changed."; exit 1; }
  if ssh-keygen -F "$address" -f "$new_known_hosts" > /dev/null 2>&1; then
    echo "The new known-hosts file still holds a key for $address; nothing changed."; exit 1
  fi
fi
[[ ! -e "$backup" ]] || { echo "$backup exists already; run this again in a second. Nothing changed."; exit 1; }
cp -p -- "$inventory" "$backup" || { echo "Could not keep a copy of $inventory; nothing changed."; exit 1; }
state=copied
# known-hosts first: should the run be killed between the two replacements, the line
# is still there and running this again finishes the job.
if [[ -n $new_known_hosts ]]; then
  # A second name for the current file, to put it back exactly as it was.
  ln -- "$known_hosts" "$saved_known_hosts" || { echo "Could not keep $known_hosts aside; nothing changed."; exit 1; }
  state=linked
  mv -f -- "$new_known_hosts" "$known_hosts" || { echo "Could not replace $known_hosts; nothing changed."; exit 1; }
  new_known_hosts='' state=key-removed
fi
if ! mv -f -- "$new_inventory" "$inventory"; then
  # finish puts known-hosts back, and says so.
  if [[ $state == copied ]]; then echo "Could not replace $inventory; nothing changed."; else echo "Could not replace $inventory."; fi
  exit 1
fi
new_inventory='' state=done
rm -f -- "$saved_known_hosts"

echo "Removed $name ansible_host=$address from $inventory; the inventory as it was is in $backup."
if [[ ${#key_lines[@]} -gt 0 ]]; then
  echo "Removed ${#key_lines[@]} trusted host key line(s) for $address from $known_hosts:"
  [[ -z $removed_keys ]] || printf '%s\n' "$removed_keys"
elif [[ $keep_key == yes ]]; then
  echo "Kept the trusted host key of $address in $known_hosts, as --keep-key asks."
elif [[ -n $sharer ]]; then
  echo "Kept the trusted host key of $address in $known_hosts: $sharer in the inventory uses that address too."
else
  echo "$known_hosts held no key for $address."
fi
echo "Only the controller changed: $name itself still has the svc_ansible account, its authorized keys, its sudo rule and its SSH drop-in."
