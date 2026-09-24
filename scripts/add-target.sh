#!/usr/bin/env bash
# Add one managed target to the local lab inventory together with its verified host key.
# Usage: sudo bash scripts/add-target.sh --name NAME --address ADDRESS --group ubuntu|enterprise_linux \
#            --fingerprint SHA256:... [--lab-dir /opt/ansible-lab] [--known-hosts /etc/semaphore/known_hosts]
#
# The fingerprint comes from the target's trusted console. Prefer the RSA key: STIG
# and FIPS crypto policies can stop a target from offering its Ed25519 host key.
#   sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub
# The script scans the target, compares every scanned key against that fingerprint, and
# records only the matching key. Without a matching fingerprint it changes nothing.
set -euo pipefail
umask 077

name= address= group= fingerprint= lab_dir=/opt/ansible-lab known_hosts=/etc/semaphore/known_hosts
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) name="$2"; shift ;;
    --address) address="$2"; shift ;;
    --group) group="$2"; shift ;;
    --fingerprint) fingerprint="$2"; shift ;;
    --lab-dir) lab_dir="$2"; shift ;;
    --known-hosts) known_hosts="$2"; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1"; exit 2 ;;
  esac
  shift
done
[[ -n "$name" && -n "$address" && -n "$group" && -n "$fingerprint" ]] || { sed -n '2,10p' "$0"; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'Run with sudo: the service known-hosts file is root-owned.'; exit 1; }
[[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo 'Inventory name must be a plain hostname-like token.'; exit 1; }
[[ "$group" == ubuntu || "$group" == enterprise_linux ]] || { echo 'Group must be ubuntu or enterprise_linux.'; exit 1; }
[[ "$fingerprint" == SHA256:* ]] || { echo 'Fingerprint must be the SHA256:... form printed by ssh-keygen -l.'; exit 1; }
inventory="$lab_dir/inventories/lab.ini"
[[ -f "$inventory" && -f "$known_hosts" ]] || { echo 'Missing inventory or known-hosts file.'; exit 1; }
if grep -qE "^[[:space:]]*$name([[:space:]]|$)" "$inventory"; then
  echo "Inventory already contains $name; edit it by hand instead."; exit 1
fi
if ssh-keygen -F "$address" -f "$known_hosts" >/dev/null; then
  echo "Known-hosts already contains $address; verify and remove the old entry before re-adding."; exit 1
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

cat "$matched" >> "$known_hosts"
python3 - "$inventory" "$group" "$name" "$address" <<'PY'
import sys
from pathlib import Path
path, group, name, address = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
lines = Path(path).read_text().splitlines()
header = f"[{group}]"
if header not in lines:
    raise SystemExit(f"Inventory lacks the {header} section")
index = lines.index(header) + 1
while index < len(lines) and lines[index].strip() and not lines[index].startswith("["):
    index += 1
lines.insert(index, f"{name} ansible_host={address}")
Path(path).write_text("\n".join(lines) + "\n")
PY
echo "Added $name ($address) to $inventory under [$group] and trusted its verified host key."
echo "Next: authorize /etc/semaphore/svc_ansible.pub for svc_ansible on the target, then run the Ping template."
