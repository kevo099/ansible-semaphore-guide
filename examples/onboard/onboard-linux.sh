#!/bin/bash
# Onboard an existing Linux VM for the guide's automation account, as root and
# without SSH: paste it into Azure Run Command (RunShellScript), or run it with
# sudo bash onboard-linux.sh on the VM itself. It is the Run Command form of
# examples/bootstrap-existing-vm.yml and is safe to run again.
#
# It creates or completes svc_ansible, authorizes exactly the public keys below,
# installs the Python bindings the lessons need, writes the sudoers rule and the
# SSH drop-in from chapter 4, checks both before SSH reloads, and prints the
# host-key fingerprints to compare with ssh-keyscan from the controller.
#
# Supported: Ubuntu 24.04, AlmaLinux, Rocky Linux and RHEL 9.

# Run Command starts scripts with /bin/sh, which is dash on Ubuntu.
if [ -z "${BASH_VERSION:-}" ]; then exec /bin/bash "$0" "$@"; fi

# 1. Replace the placeholder line with the controller's ~/.ssh/ansible_lab.pub.
#    More keys go on further lines. Keep the two END_OF_KEYS lines as they are.
PUBLIC_KEYS=$(cat <<'END_OF_KEYS'
REPLACE_WITH_AUTOMATION_PUBLIC_KEY
END_OF_KEYS
)
#
# 2. Optional: the sudo password, as a SHA-512 hash, never the password itself.
#    Make it on the controller with: openssl passwd -6   (it prompts)
#    Left empty, an existing password is kept and a new account has none, so
#    its sudo waits until you set one; chapter 13 lists the ways.
PASSWORD_HASH=''
#
# 3. Optional: the controller's address as this VM sees it, so the SSH check
#    also evaluates Match Address rules for it. Empty checks from loopback.
CONTROLLER_ADDRESS=''
#
# A managed Run Command can pass these as parameters instead, the hash as a
# protected one: ONBOARD_PUBLIC_KEYS, ONBOARD_PASSWORD_HASH, ONBOARD_CONTROLLER_ADDRESS.

set -euo pipefail
umask 022
export LC_ALL=C
PUBLIC_KEYS=${ONBOARD_PUBLIC_KEYS:-$PUBLIC_KEYS}
pasted_hash=$PASSWORD_HASH
PASSWORD_HASH=${ONBOARD_PASSWORD_HASH:-$PASSWORD_HASH}
CONTROLLER_ADDRESS=${ONBOARD_CONTROLLER_ADDRESS:-$CONTROLLER_ADDRESS}

account=svc_ansible
sudoers_file=/etc/sudoers.d/90-ansible-lab
ssh_dropin=/etc/ssh/sshd_config.d/70-ansible-lab.conf
log_file=/var/log/ansible-lab-onboard.log
work=$(mktemp -d)
cleanup() {
  rm -rf "$work"
  # Action Run Command leaves a root-only copy of the script on the VM; drop
  # this run's copy when a hash was pasted into it.
  if [ -n "$pasted_hash" ] && [[ $0 == /var/lib/waagent/run-command/download/*/script.sh ]]; then
    rm -f -- "$0"
  fi
}
trap cleanup EXIT

# Run Command returns only the last 4 KB, so the result line always comes last.
fail() { printf 'onboard: %s\n' "$*" >&2; printf 'RESULT: FAILED: %s\n' "$*"; exit 1; }
note() { printf '%s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || fail "run as root; Azure Run Command already does"

# --- Inputs, checked before anything changes -----------------------------------
key_pattern='^(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+={0,3}( [^[:cntrl:]]*)?$'
printf '%s\n' "$PUBLIC_KEYS" | sed -e 's/\r$//' -e '/^[[:space:]]*$/d' > "$work/keys"
[ -s "$work/keys" ] || fail "no public key was given"
if grep -q 'REPLACE_WITH' "$work/keys"; then
  fail "replace REPLACE_WITH_AUTOMATION_PUBLIC_KEY with the controller's public key"
fi
while IFS= read -r key; do
  [[ $key =~ $key_pattern ]] || fail "not a single-line OpenSSH public key: ${key:0:30}..."
done < "$work/keys"

# SHA-512 crypt, with rounds only in the canonical range libcrypt accepts.
# shellcheck disable=SC2016  # a literal pattern, not an expansion
hash_pattern='^\$6\$(rounds=[1-9][0-9]{3,8}\$)?[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}$'
if [ -n "$PASSWORD_HASH" ] && ! [[ $PASSWORD_HASH =~ $hash_pattern ]]; then
  fail "PASSWORD_HASH must be a SHA-512 crypt hash from openssl passwd -6"
fi
if [ -n "$CONTROLLER_ADDRESS" ] && ! [[ $CONTROLLER_ADDRESS =~ ^[0-9A-Fa-f:.]+$ ]]; then
  fail "CONTROLLER_ADDRESS must be an IP address"
fi

# --- System -----------------------------------------------------------------
# shellcheck source=/dev/null
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
  ubuntu:24.04) family=debian; ssh_unit=ssh ;;
  almalinux:9*|rocky:9*|rhel:9*) family=el; ssh_unit=sshd ;;
  *) fail "supported systems are Ubuntu 24.04 and AlmaLinux, Rocky Linux or RHEL 9, not ${PRETTY_NAME:-unknown}" ;;
esac

# Package output goes to the log so Run Command's 4 KB result stays readable.
if [ "$family" = debian ]; then
  wanted=(python3 python3-apt sudo openssh-server)
  missing=()
  for pkg in "${wanted[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed' || missing+=("$pkg")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    { apt-get -o DPkg::Lock::Timeout=600 update -q &&
      DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y -q "${missing[@]}"; } \
      >>"$log_file" 2>&1 || fail "package installation failed; see $log_file"
  fi
  # ssh.service starts on the first connection; sshd -t and -T need its runtime directory.
  install -d -m 0755 /run/sshd
else
  wanted=(python3 python3-dnf python3-libselinux sudo openssh-server)
  missing=()
  for pkg in "${wanted[@]}"; do
    rpm -q "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    dnf -y -q install "${missing[@]}" >>"$log_file" 2>&1 || fail "package installation failed; see $log_file"
  fi
fi
packages="present${missing[0]:+, installed ${missing[*]}}"

# --- Keys: readable, and at least one accepted by this SSH server -----------------
# Match rules that depend on where a client connects from are evaluated for one
# address only. Without the controller's, the check could not speak for it.
# The main file and every file it includes, as sshd reads them.
sshd_files() {
  local depth=$1 file pattern
  shift
  [ "$depth" -le 16 ] || return 0
  for file in "$@"; do
    [ -f "$file" ] || continue
    printf '%s\n' "$file"
    while read -r pattern; do
      [[ $pattern == /* ]] || pattern=/etc/ssh/$pattern
      # shellcheck disable=SC2086  # the Include pattern is a glob to expand
      sshd_files $((depth + 1)) $pattern
    done < <(awk 'tolower($1) == "include" {for (i = 2; i <= NF; i++) print $i}' "$file")
  done
}
mapfile -t config_files < <(sshd_files 1 /etc/ssh/sshd_config | sort -u)
address_rules=$(grep -hEi '^[[:space:]]*Match[[:space:]].*\b(Address|Host|LocalAddress|LocalPort|RDomain)\b' \
  "${config_files[@]}" 2>/dev/null) || address_rules=
if [ -n "$address_rules" ] && [ -z "$CONTROLLER_ADDRESS" ]; then
  fail "the SSH configuration has Match rules that depend on the client's address; set CONTROLLER_ADDRESS to the controller's address as this VM sees it"
fi
# The effective SSH settings for the account connecting from the controller.
# Every way the controller can arrive: each of this VM's addresses and SSH ports.
addr=${CONTROLLER_ADDRESS:-127.0.0.1}
read -r -a local_addresses <<<"$(hostname -I 2>/dev/null || true)"
[ "${#local_addresses[@]}" -gt 0 ] || local_addresses=(127.0.0.1)
mapfile -t ports < <(/usr/sbin/sshd -T 2>/dev/null | awk '$1 == "port" {print $2}')
[ "${#ports[@]}" -gt 0 ] || ports=(22)
contexts=()
for laddr in "${local_addresses[@]}"; do
  for lport in "${ports[@]}"; do
    contexts+=("user=$account,host=$addr,addr=$addr,laddr=$laddr,lport=$lport")
  done
done
policy_before=$(/usr/sbin/sshd -T -C "${contexts[0]}" 2>/dev/null) || fail "sshd -T could not read the SSH configuration"
accepted=$(awk '$1 == "pubkeyacceptedalgorithms" {print $2}' <<<"$policy_before")
# OpenSSH 9.1 and later report RequiredRSASize; the guide never accepts less than 2048 bits.
min_rsa=$(awk '$1 == "requiredrsasize" {print $2}' <<<"$policy_before")
[ "${min_rsa:-0}" -ge 2048 ] || min_rsa=2048
usable=0
while IFS= read -r key; do
  printf '%s\n' "$key" > "$work/one.pub"
  bits=$(ssh-keygen -lf "$work/one.pub" 2>/dev/null | awk '{print $1}') || fail "ssh-keygen cannot read key: ${key:0:30}..."
  [ -n "$bits" ] || fail "ssh-keygen cannot read key: ${key:0:30}..."
  type=${key%% *}
  if [ "$type" = ssh-rsa ]; then
    algorithms='rsa-sha2-512 rsa-sha2-256 ssh-rsa'
    if [ "$bits" -lt "$min_rsa" ]; then
      note "warning: a $bits-bit RSA key is below this server's $min_rsa-bit minimum and cannot log in"
      continue
    fi
  else
    algorithms=$type
  fi
  for algorithm in $algorithms; do
    if [[ ,$accepted, == *,"$algorithm",* ]]; then usable=$((usable + 1)); continue 2; fi
  done
  note "warning: this SSH server does not accept $type keys (a FIPS or STIG crypto policy refuses Ed25519)"
done < "$work/keys"
[ "$usable" -gt 0 ] || fail "none of the keys can log in to this SSH server; use an RSA 4096 key"

# --- Account and keys --------------------------------------------------------
if getent passwd "$account" >/dev/null; then
  account_state=present
  uid=$(id -u "$account")
  [ "$uid" -ge 1000 ] || fail "$account exists with system UID $uid; resolve that by hand"
  [ "$(getent passwd "$account" | cut -d: -f7)" = /bin/bash ] || usermod -s /bin/bash "$account"
else
  useradd --create-home --shell /bin/bash "$account"
  account_state=created
fi
uid=$(id -u "$account")
home=$(getent passwd "$account" | cut -d: -f6)
[ -d "$home" ] || fail "$account has no home directory $home"

# The account writes its own key file, so a link it planted cannot redirect root.
if runuser -u "$account" -- cmp -s - "$home/.ssh/authorized_keys" < "$work/keys" 2>/dev/null; then
  keys_state=unchanged
else
  # shellcheck disable=SC2016  # expanded by the account's own shell
  runuser -u "$account" -- /bin/bash -c '
    set -euo pipefail
    umask 077
    mkdir -p "$1/.ssh"
    chmod 0700 "$1/.ssh"
    [ ! -d "$1/.ssh/authorized_keys" ] || { echo "authorized_keys is a directory" >&2; exit 1; }
    staged=$(mktemp "$1/.ssh/.authorized_keys.XXXXXX")
    cat > "$staged"
    chmod 0600 "$staged"
    mv -f "$staged" "$1/.ssh/authorized_keys"' _ "$home" < "$work/keys" ||
    fail "could not write $home/.ssh/authorized_keys as $account"
  keys_state=replaced
fi
# SSH's StrictModes ignores keys in a writable home, .ssh or key file, so
# enforce the modes even when the keys were already right.
chmod go-w "$home"
if ! { runuser -u "$account" -- chmod 0700 "$home/.ssh" &&
        runuser -u "$account" -- chmod 0600 "$home/.ssh/authorized_keys"; }; then
  fail "could not set the modes of $home/.ssh as $account; check who owns it"
fi
if [ "$(stat -Lc '%U %a' "$home/.ssh")" != "$account 700" ] ||
   [ "$(stat -Lc '%U %a' "$home/.ssh/authorized_keys")" != "$account 600" ]; then
  fail "$home/.ssh or its authorized_keys is not owned by $account; resolve that by hand"
fi
if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then
  restorecon -RF "$home/.ssh"
fi

if [ -n "$PASSWORD_HASH" ]; then
  if [ "$(getent shadow "$account" | cut -d: -f2)" = "$PASSWORD_HASH" ]; then
    password_state="unchanged"
  else
    printf '%s:%s\n' "$account" "$PASSWORD_HASH" | chpasswd -e
    password_state="set from PASSWORD_HASH"
  fi
elif [[ $(getent shadow "$account" | cut -d: -f2) == '$'* ]]; then
  password_state="kept"
else
  password_state="NOT SET: sudo for $account will not work until you set it"
fi

# --- sudo: the account's own password, never NOPASSWD -------------------------
cat > "$work/sudoers" <<'SUDOERS'
Defaults:svc_ansible !requiretty
svc_ansible ALL=(ALL:ALL) ALL
SUDOERS
visudo -cqf "$work/sudoers" || fail "the sudoers rule does not parse"
if [ -L "$sudoers_file" ] || { [ -e "$sudoers_file" ] && [ ! -f "$sudoers_file" ]; }; then
  fail "$sudoers_file is not a regular file; resolve that by hand"
fi
if cmp -s "$work/sudoers" "$sudoers_file"; then
  sudo_state=unchanged
else
  [ ! -e "$sudoers_file" ] || cp -p "$sudoers_file" "$work/sudoers.before"
  install -o root -g root -m 0440 "$work/sudoers" "$sudoers_file"
  sudo_state=written
fi
chown root:root "$sudoers_file"
chmod 0440 "$sudoers_file"
if ! visudo -cq; then
  if [ "$sudo_state" = written ]; then
    if [ -e "$work/sudoers.before" ]; then cp -p "$work/sudoers.before" "$sudoers_file"; else rm -f "$sudoers_file"; fi
  fi
  fail "the complete sudo configuration does not parse; this run's rule was taken back"
fi
rights=$(sudo -l -U "$account")
grep -q '(ALL : ALL) ALL' <<<"$rights" || fail "$account does not have the (ALL : ALL) ALL rule; check /etc/sudoers.d"
if grep -Eq 'NOPASSWD|!authenticate' <<<"$rights"; then
  fail "a rule lets $account use sudo without its password; remove it (sudo -l -U $account shows it)"
fi
if grep -Eq '(^|[[:space:],])(rootpw|targetpw|runaspw)([[:space:],]|$)' <<<"$rights"; then
  fail "sudo asks for another account's password (rootpw, targetpw or runaspw), not $account's"
fi
if runuser -u "$account" -- sudo -k -n /usr/bin/true >/dev/null 2>&1; then
  fail "$account can sudo without a password; remove the rule that grants it"
fi

# --- SSH: key only for this account, checked before any reload ---------------
grep -Eqi '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config ||
  fail "/etc/ssh/sshd_config does not include sshd_config.d; add the drop-in by hand"
cat > "$work/dropin" <<'DROPIN'
Match User svc_ansible
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
Match all
DROPIN
if [ -L "$ssh_dropin" ] || { [ -e "$ssh_dropin" ] && [ ! -f "$ssh_dropin" ]; }; then
  fail "$ssh_dropin is not a regular file; resolve that by hand"
fi
[ ! -e "$ssh_dropin" ] || cp -p "$ssh_dropin" "$work/dropin.before"
if cmp -s "$work/dropin" "$ssh_dropin"; then
  ssh_state=unchanged
else
  install -o root -g root -m 0644 "$work/dropin" "$ssh_dropin"
  ssh_state=written
fi
chown root:root "$ssh_dropin"
chmod 0644 "$ssh_dropin"

restore_dropin() {
  if [ -e "$work/dropin.before" ]; then cp -p "$work/dropin.before" "$ssh_dropin"; else rm -f "$ssh_dropin"; fi
}
# Does the effective AuthorizedKeysFile include the file this script wrote?
reads_key_file() {
  local entry path entries
  read -r -a entries <<<"$(awk '$1 == "authorizedkeysfile" {$1 = ""; print}' <<<"$1")"
  for entry in "${entries[@]}"; do
    path=${entry//%%/$'\001'}
    path=${path//%h/$home}
    path=${path//%u/$account}
    path=${path//%U/$uid}
    path=${path//$'\001'/%}
    [[ $path == /* ]] || path=$home/$path
    [ "$path" = "$home/.ssh/authorized_keys" ] && return 0
  done
  return 1
}
ssh_problem() {
  /usr/sbin/sshd -t >"$work/sshd-t" 2>&1 || { echo "sshd -t: $(head -c 300 "$work/sshd-t")"; return; }
  local context policy line
  for context in "${contexts[@]}"; do
    policy=$(/usr/sbin/sshd -T -C "$context" 2>&1) || { echo "sshd -T: ${policy:0:300}"; return; }
    for line in 'authenticationmethods publickey' 'passwordauthentication no' \
                'kbdinteractiveauthentication no' 'pubkeyauthentication yes'; do
      grep -qx "$line" <<<"$policy" || { echo "another setting overrides '$line' for $account (${context#*,})"; return; }
    done
    reads_key_file "$policy" || { echo "AuthorizedKeysFile does not include $home/.ssh/authorized_keys"; return; }
  done
}
problem=$(ssh_problem)
if [ -n "$problem" ]; then
  [ "$ssh_state" = unchanged ] || restore_dropin
  fail "$problem; the previous drop-in was restored and SSH was not reloaded"
fi

# Reload a running server. On Ubuntu an active ssh.socket starts the server,
# with this configuration, on the next connection.
apply_ssh() {
  if systemctl is-active --quiet "$ssh_unit"; then
    systemctl reload "$ssh_unit"
  elif [ "$family" = debian ] && systemctl is-active --quiet ssh.socket; then
    true
  else
    systemctl start "$ssh_unit"
  fi
}
if ! apply_ssh >"$work/apply" 2>&1; then
  restore_dropin
  apply_ssh >/dev/null 2>&1 || true
  fail "SSH did not apply the configuration: $(head -c 200 "$work/apply"); the previous drop-in was restored"
fi
# Report the settled state, not the moment of the reload.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ "$(systemctl is-active "$ssh_unit" || true)" != reloading ] && break
  sleep 1
done
if [ "$family" = debian ]; then
  ssh_running="ssh.service $(systemctl is-active ssh.service || true), ssh.socket $(systemctl is-active ssh.socket || true)"
else
  ssh_running="sshd.service $(systemctl is-active sshd.service || true)"
fi

# --- Report -----------------------------------------------------------------
note "host: $(hostname) (${PRETTY_NAME})"
note "packages: $packages"
note "account: $account $account_state; authorized keys $keys_state:"
ssh-keygen -lf "$home/.ssh/authorized_keys" | cut -c1-110 | sed 's/^/  /'
note "password: $password_state"
note "sudo: $sudoers_file $sudo_state; $account's own password is required"
note "ssh: $ssh_dropin $ssh_state; $ssh_running; key only for $account, checked from $addr to ${#contexts[@]} local address and port pair(s)"
note "host keys to compare with ssh-keyscan from the controller:"
for pub in /etc/ssh/ssh_host_*_key.pub; do
  ssh-keygen -lf "$pub" | awk '{print "  " $1, $2, $NF}'
done
note "RESULT: OK"
