#!/usr/bin/env bash
# Print cloud-init.yaml with the controller's public key in place of its one
# placeholder, ready to give to a new VM as cloud-init data: vendor data on
# Proxmox or in a NoCloud seed, custom data on Azure.
#
# Usage, on the controller, in the guide's folder:
#   bash onboard/new-vm/fill-cloud-init.sh ~/svc_ansible.pub > ~/onboard-new-vm.yaml
# or, so that a new VM also arrives with svc_ansible's sudo password set:
#   (umask 077 && bash onboard/new-vm/fill-cloud-init.sh --with-password ~/svc_ansible.pub > ~/onboard-new-vm.yaml)
#
# The key file holds one line: on a controller made by either installer, a copy
# of /etc/semaphore/svc_ansible.pub. Nothing is written except the filled file
# on standard output; an error leaves that output empty.
#
# Without an option the filled file carries no secret and every VM made from it
# needs its sudo password set afterwards. --with-password asks for the password
# twice on the terminal and adds only its SHA-512 hash, as one more root-only
# write_files entry that the first-boot script applies and removes.
# --password-hash-file FILE takes that hash, one line from openssl passwd -6,
# from a file instead. The hash can be attacked offline wherever a copy of the
# file is kept, which is why it is opt-in; the warning printed then says where.
set -euo pipefail
export LC_ALL=C

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
template=$here/cloud-init.yaml
placeholder='"REPLACE_WITH_AUTOMATION_PUBLIC_KEY"'
# The line that ends the key's write_files entry; the hash's entry follows it.
key_entry_end='    content: *automation_key'
hash_path=/run/ansible-lab-onboard.hash
# SHA-512 crypt, with rounds only in the canonical range libcrypt accepts: the
# pattern onboard-linux.sh and the first-boot script check with.
# shellcheck disable=SC2016  # a literal pattern, not an expansion
hash_pattern='^\$6\$(rounds=[1-9][0-9]{3,8}\$)?[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}$'
# The bootstrap playbook's rule for the sudo password.
min_length=12

stop() { echo "fill-cloud-init: $*" >&2; exit 1; }
usage() {
  echo "Usage: bash $0 [--with-password | --password-hash-file HASH_FILE] PUBLIC_KEY_FILE > FILLED_FILE" >&2
  exit 2
}

ask=no hash_given=no hash_file='' key_file=''
while [[ $# -gt 0 ]]; do
  case $1 in
    --with-password) ask=yes ;;
    --password-hash-file) [[ $# -ge 2 ]] || usage; hash_given=yes; hash_file=$2; shift ;;
    -*) usage ;;
    *) [[ -z $key_file ]] || usage; key_file=$1 ;;
  esac
  shift
done
[[ -n $key_file && ! ($ask == yes && $hash_given == yes) ]] || usage

[[ -f $key_file && -r $key_file ]] || stop "cannot read $key_file"
[[ -f $template ]] || stop "missing $template"

mapfile -t keys < <(sed -e 's/\r$//' -e '/^[[:space:]]*$/d' -e '/^[[:space:]]*#/d' -- "$key_file")
[[ ${#keys[@]} -eq 1 ]] || stop "$key_file must hold exactly one public key line, and it holds ${#keys[@]}"
key=${keys[0]}
# The same single-line form onboard-linux.sh accepts.
key_pattern='^(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+={0,3}( [^[:cntrl:]]*)?$'
[[ $key =~ $key_pattern ]] || stop "$key_file is not a single-line OpenSSH public key"
ssh-keygen -l -f "$key_file" >/dev/null 2>&1 || stop "ssh-keygen cannot read the key in $key_file"
# The key goes inside a double-quoted YAML string, where these two would change it.
if [[ $key == *'"'* || $key == *\\* ]]; then
  stop 'the key comment contains a " or a \; remove the comment, the text after the base64 part'
fi

[[ $(grep -c -F -- "$placeholder" "$template") -eq 1 ]] ||
  stop "$template must contain the quoted placeholder exactly once"

# --- The opt-in password hash ------------------------------------------------
# No message names the hash or the password; neither ever reaches a command line.
# Everything that does not need the password is checked before it is asked for.
if [[ $ask == yes || $hash_given == yes ]]; then
  [[ $(grep -c -x -F -- "$key_entry_end" "$template") -eq 1 ]] ||
    stop "$template must end the key's write_files entry with '$key_entry_end' exactly once"
  ! grep -q -x -F -- "  - path: $hash_path" "$template" || stop "$template already has an entry for $hash_path"
  # A hash printed to a terminal stays in its scrollback.
  [[ ! -t 1 ]] || stop "with a password hash, send the output to a file: ... > ~/onboard-new-vm.yaml"
fi
password_hash=''
if [[ $hash_given == yes ]]; then
  [[ -f $hash_file && -r $hash_file ]] || stop "cannot read $hash_file"
  mapfile -t lines < <(sed -e 's/\r$//' -e '/^[[:space:]]*$/d' -- "$hash_file")
  if [[ ${#lines[@]} -ne 1 ]] || ! [[ ${lines[0]} =~ $hash_pattern ]]; then
    stop "$hash_file must hold one line: a SHA-512 crypt hash from openssl passwd -6"
  fi
  password_hash=${lines[0]}
elif [[ $ask == yes ]]; then
  # The prompts go to standard error and the answers come from the terminal, so
  # standard output stays the filled file.
  { : < /dev/tty; } 2>/dev/null || stop "--with-password asks on a terminal, and there is none; use --password-hash-file"
  command -v openssl >/dev/null || stop "--with-password needs openssl to make the hash"
  ask_once() {
    printf '%s' "$1" >&2
    IFS= read -r -s "$2" < /dev/tty || { echo >&2; stop "no password was given"; }
    echo >&2
  }
  # Characters, not bytes, as the playbook's length test counts them.
  characters() { local LC_ALL=C.UTF-8; echo "${#password}"; } 2>/dev/null
  password='' again=''
  ask_once "Sudo password for svc_ansible on the new VMs: " password
  ask_once "The same password again: " again
  [[ $password == "$again" ]] || stop "the two passwords differ; nothing was printed"
  [[ -n $password ]] || stop "the password is empty; nothing was printed"
  [[ $(characters) -ge $min_length ]] || stop "the password has fewer than $min_length characters; nothing was printed"
  # printf is a shell builtin, so the password reaches openssl only on its standard input.
  password_hash=$(printf '%s\n' "$password" | openssl passwd -6 -stdin 2>/dev/null) || password_hash=''
  [[ $password_hash =~ $hash_pattern ]] || stop "openssl passwd -6 did not make a SHA-512 crypt hash"
fi

if [[ -n $password_hash ]]; then
  cat >&2 <<'WARNING'
fill-cloud-init: warning: the filled file holds a hash of the sudo password, which can be attacked offline.
fill-cloud-init: Keep it readable only by people who may have the password (chmod 600): the hypervisor's
fill-cloud-init: snippet folder, the VM's seed ISO and /var/lib/cloud/instance/ inside the VM all keep a copy.
fill-cloud-init: Use a long random password, and never commit the file.
WARNING
fi

while IFS= read -r line || [[ -n $line ]]; do
  if [[ $line == *"$placeholder"* ]]; then
    printf '%s"%s"%s\n' "${line%%"$placeholder"*}" "$key" "${line#*"$placeholder"}"
  else
    printf '%s\n' "$line"
  fi
  if [[ -n $password_hash && $line == "$key_entry_end" ]]; then
    printf '%s\n' \
      "  # Added by fill-cloud-init.sh: the sudo password's hash, which the script below" \
      "  # sets for svc_ansible and then removes. Readable by root alone." \
      "  - path: $hash_path" \
      "    owner: root:root" \
      '    permissions: "0600"' \
      "    content: \"$password_hash\""
  fi
done < "$template"
