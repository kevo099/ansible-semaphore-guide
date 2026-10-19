#!/usr/bin/env bash
# Add one managed target to the local lab inventory together with its verified host key.
# Usage: sudo bash scripts/add-target.sh --name NAME --address ADDRESS --group ubuntu|enterprise_linux \
#            --fingerprint SHA256:... [--lab-dir /opt/ansible-lab] [--known-hosts /etc/semaphore/known_hosts]
#    or: sudo bash scripts/add-target.sh --from-info [--address ADDRESS] [--lab-dir DIR] [--known-hosts FILE]
#
# --from-info reads what the onboarding scripts print on the VM: paste their name=,
# address=, group= and fingerprint= lines, then press Ctrl-D; Ctrl-C and then Ctrl-D
# cancels. A VM's output is not trusted, so it is data for this script and never a
# command for a shell: the script reads the whole paste before anything else, on a
# terminal discards whatever still arrives after it, takes only those four values,
# checks them as it checks the options, and ignores every other line. An option fills
# in a value the paste lacks, such as --address; a value given both ways is refused.
#
# The fingerprint comes from the target through a trusted channel: its console or
# Azure Run Command. Prefer the RSA key: STIG and FIPS crypto policies can stop a
# target from offering its Ed25519 host key.
#   sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub
# The script scans the target, compares every scanned key against that fingerprint, and
# keeps only the matching key. It adds the inventory line first and records that key
# only after the edit succeeds, so a mismatch or a missing group section changes nothing.
# Running it again for a host it added, with the same values, changes nothing.
set -euo pipefail
umask 077
# Match bytes: in a UTF-8 locale, [A-Za-z] also matches other alphabets' look-alike letters.
export LC_ALL=C

# Print the comment block at the top of this file.
usage() { sed -n '2,/^[^#]/{/^#/p}' "$0"; }
missing() { echo "$1 needs a value."; usage; exit 2; }

# With --from-info, read the paste first and to its end, so that no part of it is
# left for the shell when this script stops, whatever the reason.
from_info=no
for argument in "$@"; do
  [[ $argument != --from-info ]] || from_info=yes
done
pasted='' cancelled=no
if [[ $from_info == yes ]]; then
  if [[ -t 0 ]]; then
    # A control character in the paste must not stop the reading: Ctrl-\ and Ctrl-Z do
    # nothing, and a Ctrl-C is only noted, so that it cancels once the input has ended.
    trap 'cancelled=yes' INT
    trap '' QUIT TSTP
  fi
  # Keep at most 64 KiB; one byte more means the paste is longer. A NUL becomes a space.
  # On a terminal the reader ignores Ctrl-C itself, and asks for the paste only then.
  pasted=$(if [[ -t 0 ]]; then
             trap '' INT
             echo "To cancel, press Ctrl-C and then Ctrl-D." >&2
             echo "Paste the name=, address=, group= and fingerprint= lines the VM printed, then press Ctrl-D:" >&2
           fi
           head -c 65537 | tr '\0' ' '; echo .)
  pasted=${pasted%.}
  # The input has ended; from here Ctrl-C does nothing, so the rest is always discarded.
  [[ ! -t 0 ]] || trap '' INT
  too_long=no
  if [[ $(printf '%s' "$pasted" | wc -c) -gt 65536 ]]; then
    too_long=yes
    cat > /dev/null
  fi
  if [[ -t 0 ]]; then
    # A Ctrl-D inside the paste ends the reading early, and the rest of a long paste, or
    # of one over a slow link, can still be arriving: discard what comes, unechoed, until
    # the terminal has been quiet for a second.
    python3 -c '
import os, termios
saved = termios.tcgetattr(0)
quiet = termios.tcgetattr(0)
quiet[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG)
quiet[6][termios.VMIN], quiet[6][termios.VTIME] = 0, 10
termios.tcsetattr(0, termios.TCSANOW, quiet)
try:
    while os.read(0, 65536):
        pass
finally:
    termios.tcsetattr(0, termios.TCSAFLUSH, saved)' 2>/dev/null || true
    trap - INT QUIT TSTP
  fi
  [[ $cancelled == no ]] || { echo "Cancelled; nothing changed."; exit 130; }
  [[ $too_long == no ]] || { echo "The paste is longer than 64 KiB; paste one VM's lines at a time."; exit 2; }
fi

name='' address='' group='' fingerprint='' lab_dir=/opt/ansible-lab known_hosts=/etc/semaphore/known_hosts
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) [[ $# -ge 2 ]] || missing "$1"; name="$2"; shift ;;
    --address) [[ $# -ge 2 ]] || missing "$1"; address="$2"; shift ;;
    --group) [[ $# -ge 2 ]] || missing "$1"; group="$2"; shift ;;
    --fingerprint) [[ $# -ge 2 ]] || missing "$1"; fingerprint="$2"; shift ;;
    --lab-dir) [[ $# -ge 2 ]] || missing "$1"; lab_dir="$2"; shift ;;
    --known-hosts) [[ $# -ge 2 ]] || missing "$1"; known_hosts="$2"; shift ;;
    --from-info) ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; exit 2 ;;
  esac
  shift
done
if [[ $from_info == yes ]]; then
  # A value counts only on a whole line of this form: an optional "onboard:" prefix,
  # as cloud-init logs it, then one of the four keys and its value.
  info_line='^[[:space:]]*(onboard:[[:space:]]+)?(name|address|group|fingerprint)=(.*[^[:space:]])[[:space:]]*$'
  declare -A info=()
  while IFS= read -r line; do
    line=${line%$'\r'}
    [[ $line =~ $info_line ]] || continue
    key=${BASH_REMATCH[2]}
    [[ -z ${info[$key]+set} ]] || { echo "The paste has more than one $key= line; paste one VM's lines at a time."; exit 2; }
    info[$key]=${BASH_REMATCH[3]}
  done <<< "$pasted"
  for key in name address group fingerprint; do
    if [[ -n ${info[$key]+set} ]]; then
      [[ -z ${!key} ]] || { echo "The $key is both in the paste and given with --$key; give it once."; exit 2; }
      printf -v "$key" '%s' "${info[$key]}"
    elif [[ -z ${!key} ]]; then
      echo "The paste has no $key= line; give that value with --$key."; exit 2
    fi
  done
fi
[[ -n "$name" && -n "$address" && -n "$group" && -n "$fingerprint" ]] || { usage; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'Run with sudo: the service known-hosts file is root-owned.'; exit 1; }
# The values end up in the inventory and in ssh-keyscan's arguments: plain tokens only.
[[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo 'Inventory name must be a plain hostname-like token.'; exit 1; }
[[ "$address" =~ ^[A-Za-z0-9:][A-Za-z0-9.:-]*$ ]] || { echo 'Address must be an IP address or a DNS name.'; exit 1; }
[[ "$group" == ubuntu || "$group" == enterprise_linux ]] || { echo 'Group must be ubuntu or enterprise_linux.'; exit 1; }
[[ "$fingerprint" =~ ^SHA256:[A-Za-z0-9+/]+$ ]] || { echo 'Fingerprint must be the SHA256:... form printed by ssh-keygen -l.'; exit 1; }
# Shown only once checked, so nothing unchecked from the VM reaches the terminal.
[[ $from_info == no ]] || echo "Using name=$name address=$address group=$group fingerprint=$fingerprint"
inventory="$lab_dir/inventories/lab.ini"
[[ -f "$inventory" && -f "$known_hosts" ]] || { echo 'Missing inventory or known-hosts file.'; exit 1; }
# Ansible runs delegate_to: localhost tasks on a host of that name instead of the controller.
if [[ "$name" == localhost || "$name" == 127.0.0.1 ]]; then
  echo "$name is the name Ansible gives the controller; choose another name."; exit 1
fi
# A host named like a group, such as lab, would make --limit lab select that host alone.
if [[ "$name" == all || "$name" == ungrouped ]] || awk -v n="$name" '
    match($0, /^[[:space:]]*\[[^]]+\]/) {
      header = substr($0, RSTART, RLENGTH); sub(/^[[:space:]]*\[/, "", header); sub(/\]$/, "", header)
      sub(/:.*/, "", header); if (header == n) found = 1
    }
    END {exit !found}' "$inventory"; then
  echo "$name is also the name of an inventory group; choose another name."; exit 1
fi
# Compare whole fields as text: a dot in the name is not a wildcard, and names that
# look like numbers (10 and 010) stay different.
existing=$(awk -v n="$name" '$1 == (n "") {print $1, $2; exit}' "$inventory")
owner=$(awk -v a="ansible_host=$address" -v n="$name" '$1 != (n "") {for (i = 2; i <= NF; i++) if ($i == a) {print $1; exit}}' "$inventory")
trusted=$(ssh-keygen -F "$address" -f "$known_hosts" 2>/dev/null | grep -v '^#' || true)
trusted_matches=no
if [[ -n "$trusted" ]] && printf '%s\n' "$trusted" | ssh-keygen -lf - 2>/dev/null | grep -qF -- " $fingerprint "; then
  trusted_matches=yes
fi
if [[ -n "$existing" ]]; then
  if [[ "$existing" == "$name ansible_host=$address" && $trusted_matches == yes ]]; then
    echo "Already present: $name ($address) is in $inventory and its verified key is trusted; nothing changed."
    exit 0
  fi
  echo "Inventory already contains $name with other settings ($existing); edit it by hand instead."; exit 1
fi
if [[ -n "$owner" ]]; then
  echo "Inventory already lists $address as $owner; edit it by hand instead."; exit 1
fi
if [[ -n "$trusted" && $trusted_matches == no ]]; then
  echo "Known-hosts already contains a different key for $address. After verifying why its key changed,"
  echo "remove the old entry and give the rewritten file back to the service before re-adding:"
  echo "  sudo ssh-keygen -R $address -f $known_hosts"
  echo "  sudo chown root:semaphore $known_hosts && sudo chmod 0640 $known_hosts"
  exit 1
fi

scan=$(mktemp)
trap 'rm -f "$scan"' EXIT
ssh-keyscan -T 10 -t ed25519,rsa,ecdsa -- "$address" > "$scan" 2>/dev/null || true
[[ -s "$scan" ]] || { echo "No SSH host key received from $address."; exit 1; }
matched=$(mktemp)
trap 'rm -f "$scan" "$matched"' EXIT
while read -r line; do
  [[ -n "$line" && "$line" != \#* ]] || continue
  if printf '%s\n' "$line" | ssh-keygen -lf - | grep -qF -- " $fingerprint "; then
    printf '%s\n' "$line" >> "$matched"
  fi
done < "$scan"
if [[ ! -s "$matched" ]]; then
  echo "No scanned key matched $fingerprint. Scanned fingerprints (unverified):"
  ssh-keygen -lf "$scan" | awk '{print "  " $2 " " $4}'
  exit 1
fi

python3 - "$inventory" "$group" "$name" "$address" <<'PY'
import re
import sys
from pathlib import Path
path, group, name, address = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
lines = Path(path).read_text().splitlines()
# Read section headers as Ansible does: surrounding spaces and a trailing # comment
# are allowed. Ansible cannot parse a header followed by a ; comment.
header = re.compile(r"\[" + re.escape(group) + r"\]\s*(?:#.*)?")
starts = [i for i, line in enumerate(lines) if header.fullmatch(line.strip())]
if not starts:
    raise SystemExit(f"Inventory lacks the [{group}] section; nothing was changed.")
index = starts[0] + 1
while index < len(lines) and lines[index].strip() and not lines[index].lstrip().startswith("["):
    index += 1
lines.insert(index, f"{name} ansible_host={address}")
Path(path).write_text("\n".join(lines) + "\n")
PY
# Trust the key only now, so a refused inventory edit leaves known_hosts unchanged.
[[ $trusted_matches == yes ]] || cat "$matched" >> "$known_hosts"
echo "Added $name ($address) to $inventory under [$group] and trusted its verified host key."
echo "Next: run the Ping template, which covers every host in the lab group. If $name fails with Permission denied (publickey),"
echo "svc_ansible on $name lacks the key 'sudo cat /etc/semaphore/svc_ansible.pub' shows; if sudo asks for a"
echo "password, give Semaphore the targets' sudo password, as chapter 3b shows."
