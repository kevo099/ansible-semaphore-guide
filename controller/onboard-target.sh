#!/usr/bin/env bash
# Prepare machines that already exist for the guide's automation account and add
# them to the lab inventory, in one command on the controller.
# Usage: bash controller/onboard-target.sh ADMIN@ADDRESS [ADMIN@ADDRESS ...]
#            [--name NAME] [--keep-password] [--extra-key FILE] [--lab-dir /opt/ansible-lab]
#
# Run it as your administrator account, without sudo, in the guide's folder. For
# each machine it copies onboard/existing/onboard-linux.sh and the service key
# there over SSH as that machine's administrator, runs the script with sudo, and
# gives the lines it prints to add-target.sh --from-info, which checks them and
# adds the machine with its verified host key. It asks once for the sudo password
# that svc_ansible gets on these machines and sends only its hash; with
# --keep-password it leaves the password each account already has.
#
# SSH asks you to confirm a machine's host key the first time it connects.
# Compare the RSA fingerprint it shows with the one on the machine's console:
#   sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub
# and answer yes only when they are the same. The fingerprint that add-target.sh
# then trusts for Semaphore is read over that verified connection, and it uses
# the address you typed here, not one the machine reports.
#
# --name NAME        the inventory name, for one machine: needed when its hostname
#                    is one the inventory reserves, such as localhost or ubuntu
# --keep-password    do not ask for a sudo password; keep each account's own
# --extra-key FILE   also authorize the public key in FILE for svc_ansible, such as
#                    your own key for the command-line lessons; repeat it for more.
#                    The account's authorized keys become exactly the service key
#                    and these, so give them on every run for that machine.
# --lab-dir DIR      a lab folder other than /opt/ansible-lab
# Running it again for a machine is safe: the script reports what is unchanged,
# and add-target.sh says "Already present".
set -euo pipefail
umask 077
# Match bytes: in a UTF-8 locale, [A-Za-z] also matches other alphabets' look-alike letters.
export LC_ALL=C

usage() { sed -n '2,/^[^#]/{/^#/p}' "$0"; }
stop() { echo "$*" >&2; exit 1; }

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
onboard_script=$here/../onboard/existing/onboard-linux.sh
service_key=/etc/semaphore/svc_ansible.pub

targets=() extra_keys=() name='' lab_dir='' keep_password=no
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name|--lab-dir|--extra-key)
      [[ $# -ge 2 && -n $2 && $2 != -* ]] || { echo "$1 needs a value."; exit 2; }
      case "$1" in
        --name) name=$2 ;;
        --lab-dir) lab_dir=$2 ;;
        --extra-key) extra_keys+=("$2") ;;
      esac
      shift ;;
    --keep-password) keep_password=yes ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "Unknown option: $1"; exit 2 ;;
    *) targets+=("$1") ;;
  esac
  shift
done
[[ ${#targets[@]} -gt 0 ]] || { usage; exit 2; }
[[ -z $name || ${#targets[@]} -eq 1 ]] || { echo '--name names one machine; give one ADMIN@ADDRESS with it.'; exit 2; }
[[ -z $name || $name =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo 'The name must be a plain hostname-like token.'; exit 2; }
for target in "${targets[@]}"; do
  # These end up in ssh's and add-target.sh's arguments: plain tokens only.
  [[ $target =~ ^[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9:][A-Za-z0-9.:-]*$ ]] ||
    { echo "Give each machine as ADMIN@ADDRESS, the administrator's login and an IP address or DNS name: $target"; exit 2; }
  [[ ${target%%@*} != svc_ansible ]] ||
    { echo 'Log in as the machine'"'"'s administrator, not as svc_ansible, the account this prepares.'; exit 2; }
done
[[ $(id -u) != 0 ]] || stop 'Run it as your administrator account, without sudo: it uses your SSH keys and known hosts, and asks for sudo where it needs it.'
[[ -f $onboard_script ]] || stop "Missing $onboard_script; run this from a complete copy of the guide."
for tool in ssh scp ssh-keygen sudo; do
  command -v "$tool" >/dev/null || stop "This needs $tool."
done

work=$(mktemp -d)
masters=()
cleanup() {
  local target
  for target in "${masters[@]}"; do
    ssh -o ControlPath="$work/%C" -O exit "$target" 2>/dev/null || true
  done
  rm -rf "$work"
}
trap cleanup EXIT

# The key Semaphore logs in with, read from its source rather than from a copy that
# an earlier installation may have left in a home folder.
echo "Reading the service key $service_key, which needs sudo on this controller."
# One key per line, each line ended: a file without a final newline must not run into the next key.
key_lines() { awk '{ sub(/\r$/, "") } NF' < "$1"; }
# shellcheck disable=SC2024  # the copy is this account's own file; only the read needs root
sudo cat "$service_key" > "$work/service-key" || stop "Could not read $service_key. Was this controller made by the guide's installer?"
ssh-keygen -l -f "$work/service-key" >/dev/null 2>&1 || stop "$service_key is not a public key ssh-keygen can read."
key_lines "$work/service-key" > "$work/svc_ansible.pub"
# The script on the machine replaces the account's keys with exactly this list.
for extra_key in "${extra_keys[@]}"; do
  [[ -f $extra_key && -r $extra_key ]] || stop "Cannot read the key file $extra_key."
  ssh-keygen -l -f "$extra_key" >/dev/null 2>&1 || stop "$extra_key is not a public key ssh-keygen can read."
  grep -q 'PRIVATE KEY' -- "$extra_key" && stop "$extra_key is a private key; give its .pub file."
  key_lines "$extra_key" >> "$work/svc_ansible.pub"
done

script_options=(--keys svc_ansible.pub)
files=("$onboard_script" "$work/svc_ansible.pub")
if [[ $keep_password == no ]]; then
  [[ -t 0 ]] || stop 'Run it from a terminal to be asked for the sudo password, or pass --keep-password.'
  command -v openssl >/dev/null || stop 'This needs openssl to hash the sudo password.'
  echo 'The sudo password that svc_ansible gets on these machines: one shared lab password,'
  echo 'which Semaphore needs once afterwards. Save it in your password manager.'
  IFS= read -rs -p 'Sudo password for svc_ansible, 12 characters or more: ' first || stop 'No password was entered.'
  echo
  IFS= read -rs -p 'The same password again: ' second || stop 'No password was entered.'
  echo
  [[ $first == "$second" ]] || stop 'The two entries differ; nothing was changed. Run it again.'
  # Characters, not bytes, as the bootstrap playbook counts them.
  [[ $(printf '%s' "$first" | LC_ALL=C.UTF-8 wc -m) -ge 12 ]] || stop 'The password has fewer than 12 characters; nothing was changed.'
  # On standard input, so that the password never appears in a command line.
  printf '%s' "$first" | openssl passwd -6 -stdin > "$work/sudo-password.hash" || stop 'openssl could not hash the password.'
  first='' second=''
  script_options+=(--password-hash-file sudo-password.hash)
  files+=("$work/sudo-password.hash")
fi

failed=() added=()
for target in "${targets[@]}"; do
  address=${target#*@}
  echo
  echo "=== $target"
  ssh_options=(-o ControlMaster=auto -o ControlPath="$work/%C" -o ControlPersist=120 -o StrictHostKeyChecking=ask)
  if ! ssh-keygen -F "$address" >/dev/null 2>&1; then
    echo "This account has not connected to $address before. SSH shows its RSA key fingerprint next."
    echo 'Compare it with the machine'"'"'s console, sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub,'
    echo 'and answer yes only when they are the same.'
    # The RSA key, so that the fingerprint is the one the console command and add-target.sh use.
    # shellcheck disable=SC2054  # one option value, with its own comma
    ssh_options+=(-o HostKeyAlgorithms=rsa-sha2-512,rsa-sha2-256)
  fi
  # One connection for the three steps, so a password login is typed once. The
  # folder's name is the machine's answer: accept only what mktemp prints.
  # sh -c, because an administrator's login shell need not be a POSIX shell.
  remote_dir=$(ssh "${ssh_options[@]}" "$target" "sh -c 'umask 077 && mktemp -d'") || { echo "Could not log in to $target."; failed+=("$target"); continue; }
  masters+=("$target")
  remote_dir=${remote_dir%$'\r'}
  if ! [[ $remote_dir =~ ^/[A-Za-z0-9._/-]+$ ]]; then
    echo "$target answered with something other than a folder name; nothing was changed there."
    failed+=("$target"); continue
  fi
  # scp splits its destination at the first colon: an IPv6 address goes in brackets.
  copy_to=$target
  [[ $address != *:* ]] || copy_to="${target%%@*}@[$address]"
  if ! scp -q -o ControlPath="$work/%C" "${files[@]}" "$copy_to:$remote_dir/"; then
    echo "Could not copy the script to $target."
    ssh "${ssh_options[@]}" "$target" "sh -c 'rm -rf -- $remote_dir'" || true
    failed+=("$target"); continue
  fi
  # The script runs in its folder, so the options name the files without a path.
  # SSH_CONNECTION starts with this controller's address as the machine sees it.
  # The folder, which holds the password's hash, goes on every way out: when the
  # script ends, on Ctrl-C at the machine's sudo prompt, and when the connection drops.
  remote_command="sh -c 'cleanup() { cd / && rm -rf -- $remote_dir; }; trap \"cleanup; exit 130\" HUP INT TERM; cd $remote_dir && sudo bash onboard-linux.sh ${script_options[*]} --controller-address \"\${SSH_CONNECTION%% *}\"; status=\$?; cleanup; exit \$status'"
  # -t gives sudo on the machine a terminal for its own password prompt.
  if ! ssh -t "${ssh_options[@]}" "$target" "$remote_command" | tee "$work/output"; then
    echo "The script did not finish on $target; its last line above says why."
    # Once more over the connection that is still open, in case the shell there was killed.
    ssh -o BatchMode=yes "${ssh_options[@]}" "$target" "sh -c 'rm -rf -- $remote_dir'" 2>/dev/null || true
    failed+=("$target"); continue
  fi
  tr -d '\r' < "$work/output" > "$work/output.clean"
  if [[ $(grep -v '^[[:space:]]*$' "$work/output.clean" | tail -n 1) != 'RESULT: OK' ]]; then
    echo "The script did not report RESULT: OK on $target; not adding it."
    failed+=("$target"); continue
  fi
  # Data for add-target.sh, which checks every value. The address is the one typed
  # here, and --name replaces the machine's own name.
  if [[ -n $name ]]; then
    grep -E '^(group|fingerprint)=' "$work/output.clean" > "$work/lines" || true
  else
    grep -E '^(name|group|fingerprint)=' "$work/output.clean" > "$work/lines" || true
  fi
  add_options=(--from-info --address "$address")
  [[ -z $name ]] || add_options+=(--name "$name")
  [[ -z $lab_dir ]] || add_options+=(--lab-dir "$lab_dir")
  echo
  echo "Nothing to paste: this command passes those lines on. Adding $address on this controller, which needs sudo here:"
  # add-target.sh's closing hint is for a run by hand; this command ends with its own.
  if sudo bash "$here/add-target.sh" "${add_options[@]}" < "$work/lines" | sed -e '/^Next: run the Ping template/,$d'; then
    added+=("$target")
  else
    echo "$target is prepared, but add-target.sh did not add it; its message above says what it needs."
    [[ -n $name ]] || echo "If it asks for a name, run this again for that machine alone with --name NAME."
    failed+=("$target")
  fi
done

echo
[[ ${#added[@]} -eq 0 ]] || echo "Prepared and in the inventory: ${added[*]}"
if [[ ${#failed[@]} -gt 0 ]]; then
  echo "Not finished: ${failed[*]}"
  exit 1
fi
echo 'Next: give Semaphore the sudo password once, sudo python3.12 controller/lab-sudo.py,'
echo 'then run the Ping and Baseline preview templates.'
