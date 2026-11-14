#!/usr/bin/env bash
# First boot of a new controller VM. cloud-init runs this once, as root, after
# controller/first-boot/user-data.yaml has installed Git and fetched this copy of
# the guide. It runs the installer with the values of
# /etc/ansible-semaphore-guide/first-boot.conf, then the readiness check, and
# writes what happened to /var/log/ansible-guide-first-boot.log. It asks nothing
# and prints no secret. After a stop, fix its cause and run it again:
#   sudo bash controller/first-boot.sh
# A second run never runs the installer twice: on an installed controller it
# finishes an HTTPS publication that failed, and checks.
set -euo pipefail

conf=/etc/ansible-semaphore-guide/first-boot.conf
log=/var/log/ansible-guide-first-boot.log
marker=/etc/semaphore/.guide-project-seeded
exposure=/etc/semaphore/exposure
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

[[ $(id -u) == 0 ]] || { echo 'Run with sudo on the controller.'; exit 1; }
# cloud-init runs its commands without a home folder set, which Git and pip expect.
export HOME=/root

# The last line of that name wins; a pasted file may carry carriage returns.
value() { sed -n "s/^$1=//p" "$conf" | tr -d '\r' | sed 's/[[:space:]]*$//' | tail -n 1; }

stop() {
  printf 'first-boot: RESULT: STOPPED: %s\n' "$*"
  exit 1
}

main() {
  printf 'first-boot: started %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  [[ -r $conf ]] || stop "there is no $conf; give the VM controller/first-boot/user-data.yaml when you create it"
  local admin expose address installer id address_option=() options=()
  admin=$(value admin) expose=$(value expose) address=$(value address)
  : "${expose:=tunnel}"

  [[ $admin != REPLACE_WITH_ADMIN_LOGIN && $admin =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] ||
    stop "admin= in $conf must be the login of this VM's administrator; it still holds the placeholder or is empty"
  [[ $admin != root && $admin != semaphore ]] ||
    stop "admin= in $conf must be your own administrator account, not $admin"
  getent passwd "$admin" >/dev/null ||
    stop "this VM has no account $admin; set admin= in $conf to the administrator the VM was created with"
  [[ $expose == tunnel || $expose == https ]] || stop "expose= in $conf must be tunnel or https"
  [[ -z $address || $expose == https ]] || stop "address= in $conf is only for expose=https"
  # The same check as controller/expose-semaphore.sh, which would otherwise refuse the value
  # only as the installer's last step.
  if [[ $address =~ ^[0-9.]+$ || $address == *:* ]]; then
    [[ $address != *%* ]] && python3 -I -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$address" 2>/dev/null ||
      stop "address= in $conf is not a valid IP address; give one without a port or a %zone suffix, or a DNS name"
  elif [[ -n $address && ! $address =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
    stop "address= in $conf must be an IP address or a DNS name, without a port and without https://"
  fi
  [[ -z $address ]] || address_option=(--address "$address")
  [[ $expose != https ]] || options=(--expose https "${address_option[@]}")

  if [[ -e $marker || -e /etc/semaphore/.practice-project-seeded ]]; then
    printf 'first-boot: this controller is already installed; the installer is not run again\n'
    if [[ $expose == https && $(cat "$exposure" 2>/dev/null) != https ]]; then
      # The installer's last step failed on an earlier run; it says to run only this again.
      printf 'first-boot: publishing the UI over HTTPS, which an earlier run did not finish\n'
      bash "$script_dir/expose-semaphore.sh" --mode https "${address_option[@]}" ||
        stop "publishing the UI over HTTPS failed, for the reason shown above; fix it and run this again: sudo bash controller/first-boot.sh"
    fi
  else
    # shellcheck disable=SC1091
    id=$(. /etc/os-release && printf '%s' "${ID:-}")
    case "$id" in
      ubuntu) installer=install-controller.sh ;;
      rhel|almalinux|rocky) installer=install-controller-el9.sh ;;
      *) stop "this system (ID=$id in /etc/os-release) is none of Ubuntu, RHEL, AlmaLinux and Rocky Linux" ;;
    esac
    printf 'first-boot: running %s --apply --editor %s %s\n' "$installer" "$admin" "${options[*]}"
    if ! bash "$script_dir/$installer" --apply --editor "$admin" "${options[@]}"; then
      # The installer publishes over HTTPS last, after the controller is complete and seeded.
      [[ ! -e $marker ]] ||
        stop "the controller is installed, but publishing the UI over HTTPS failed, for the reason shown above; fix it and run this again: sudo bash controller/first-boot.sh"
      stop "the installer ended with an error, shown above. docs/stage-1-controller.md, \"When it fails\", lists the causes; the installer does not run twice on one VM, so after a failure half way a new VM is the short way"
    fi
  fi

  python3.12 "$script_dir/check-controller.py" >/dev/null ||
    stop "the controller is installed, but its readiness check fails; see which check with: sudo python3.12 controller/check-controller.py"
  printf 'first-boot: the readiness check passed\n'
  printf 'first-boot: RESULT: OK\n'
  if [[ $expose == https ]]; then
    printf 'first-boot: next, browse to the https address the installer printed above and log in as admin.\n'
  else
    printf 'first-boot: next, open the SSH tunnel of docs/stage-1-controller.md, "Open Semaphore", and log in as admin.\n'
  fi
  printf 'first-boot: the initial password: sudo cat /etc/semaphore/initial-admin-password\n'
}

# The log repeats the installer's output, which names accounts and paths but no secret.
# cloud-init keeps the same lines in /var/log/cloud-init-output.log and on the console.
[[ -e $log ]] || install -m 0600 /dev/null "$log"
main 2>&1 | tee -a "$log"
exit "${PIPESTATUS[0]}"
