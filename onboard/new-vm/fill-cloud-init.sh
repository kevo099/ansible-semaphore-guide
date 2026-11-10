#!/usr/bin/env bash
# Print cloud-init.yaml with the controller's public key in place of its one
# placeholder, ready to give to a new VM as cloud-init user data.
#
# Usage, on the controller, in the guide's folder:
#   bash onboard/new-vm/fill-cloud-init.sh ~/svc_ansible.pub > ~/onboard-new-vm.yaml
#
# The key file holds one line: on a controller made by either installer, a copy
# of /etc/semaphore/svc_ansible.pub. Nothing is written except the filled file
# on standard output; an error leaves that output empty.
set -euo pipefail
export LC_ALL=C

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
template=$here/cloud-init.yaml
placeholder='"REPLACE_WITH_AUTOMATION_PUBLIC_KEY"'

stop() { echo "fill-cloud-init: $*" >&2; exit 1; }

[[ $# -eq 1 && $1 != -* ]] || { echo "Usage: bash $0 PUBLIC_KEY_FILE > FILLED_FILE" >&2; exit 2; }
[[ -f $1 && -r $1 ]] || stop "cannot read $1"
[[ -f $template ]] || stop "missing $template"

mapfile -t keys < <(sed -e 's/\r$//' -e '/^[[:space:]]*$/d' -e '/^[[:space:]]*#/d' -- "$1")
[[ ${#keys[@]} -eq 1 ]] || stop "$1 must hold exactly one public key line, and it holds ${#keys[@]}"
key=${keys[0]}
# The same single-line form onboard-linux.sh accepts.
key_pattern='^(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+={0,3}( [^[:cntrl:]]*)?$'
[[ $key =~ $key_pattern ]] || stop "$1 is not a single-line OpenSSH public key"
ssh-keygen -l -f "$1" >/dev/null 2>&1 || stop "ssh-keygen cannot read the key in $1"
# The key goes inside a double-quoted YAML string, where these two would change it.
if [[ $key == *'"'* || $key == *\\* ]]; then
  stop 'the key comment contains a " or a \; remove the comment, the text after the base64 part'
fi

[[ $(grep -c -F -- "$placeholder" "$template") -eq 1 ]] ||
  stop "$template must contain the quoted placeholder exactly once"

while IFS= read -r line || [[ -n $line ]]; do
  if [[ $line == *"$placeholder"* ]]; then
    printf '%s"%s"%s\n' "${line%%"$placeholder"*}" "$key" "${line#*"$placeholder"}"
  else
    printf '%s\n' "$line"
  fi
done < "$template"
