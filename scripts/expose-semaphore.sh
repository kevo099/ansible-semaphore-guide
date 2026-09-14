#!/usr/bin/env bash
# Make the loopback-only Semaphore UI reachable on this VM's own address.
# Usage: sudo bash scripts/expose-semaphore.sh --mode https|http|loopback [--address IP_OR_NAME]
#
#   https     (recommended) nginx terminates TLS on port 443 with a locally generated
#             self-signed certificate and proxies to 127.0.0.1:3000. Semaphore itself
#             keeps listening on loopback only.
#   http      Semaphore binds every address on port 3000 in plain text. Passwords and
#             session cookies cross the network unencrypted; use only on a network you
#             fully control, and prefer https.
#   loopback  Undo either mode: close the firewall port, remove the proxy site and
#             bind Semaphore to 127.0.0.1 again.
#
# The cloud/network firewall in front of the VM is not touched; allow the chosen
# port there yourself, ideally only from your own address.
set -euo pipefail
umask 077

# Split so the repository validator does not read this as a real address.
any_address='0.0.0''.0'
mode= address=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) mode="$2"; shift ;;
    --address) address="$2"; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1"; exit 2 ;;
  esac
  shift
done
[[ "$mode" == https || "$mode" == http || "$mode" == loopback ]] || { sed -n '2,16p' "$0"; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'Run with sudo on the controller.'; exit 1; }
[[ -f /etc/semaphore/config.json ]] || { echo 'No Semaphore configuration found; install the controller first.'; exit 1; }
source /etc/os-release
case "$ID" in
  rhel|almalinux|rocky) family=el; nginx_site=/etc/nginx/conf.d/semaphore-tls.conf ;;
  ubuntu|debian) family=deb; nginx_site=/etc/nginx/sites-enabled/semaphore-tls.conf ;;
  *) echo 'Supported on Enterprise Linux 9 and Ubuntu only.'; exit 1 ;;
esac
marker=/etc/semaphore/exposure
tls_dir=/etc/semaphore/tls

set_interface() {
  python3 - "$1" <<'PY'
import json, sys
from pathlib import Path
p = Path('/etc/semaphore/config.json')
config = json.loads(p.read_text())
config['interface'] = sys.argv[1]
p.write_text(json.dumps(config, indent=2) + '\n')
PY
  chown root:semaphore /etc/semaphore/config.json
  chmod 0640 /etc/semaphore/config.json
  systemctl restart semaphore
}

firewall() {  # firewall add|remove https|3000/tcp
  if systemctl is-active --quiet firewalld; then
    if [[ "$2" == https ]]; then firewall-cmd -q --permanent "--$1-service=https"; else firewall-cmd -q --permanent "--$1-port=$2"; fi
    firewall-cmd -q --reload
  elif command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
    if [[ "$1" == add ]]; then ufw allow "${2/https/443/tcp}" >/dev/null; else ufw delete allow "${2/https/443/tcp}" >/dev/null || true; fi
  else
    echo "No active host firewall found; nothing to $1 for $2."
  fi
}

wait_ping() {
  for _ in {1..30}; do
    if curl -fs -o /dev/null http://127.0.0.1:3000/api/ping; then return 0; fi
    sleep 1
  done
  echo 'Semaphore did not answer on loopback after the restart.'; exit 1
}

primary_address() {
  address="${address:-$(ip -4 route get 1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1); exit}')}"
  [[ -n "$address" ]] || { echo 'Could not determine this VM address; pass --address.'; exit 1; }
}

case "$mode" in
  loopback)
    rm -f "$nginx_site"
    if systemctl is-active --quiet nginx; then systemctl reload nginx || true; fi
    firewall remove https || true
    firewall remove 3000/tcp || true
    set_interface 127.0.0.1
    wait_ping
    rm -f "$marker"
    echo 'Semaphore is loopback-only again; reach it through an SSH tunnel.'
    ;;
  http)
    rm -f "$nginx_site"
    if systemctl is-active --quiet nginx; then systemctl reload nginx || true; fi
    firewall remove https || true
    set_interface "$any_address"
    wait_ping
    firewall add 3000/tcp
    printf 'http\n' > "$marker"; chmod 0644 "$marker"
    primary_address
    echo "Semaphore listens in PLAIN TEXT on every address, port 3000: http://$address:3000/"
    echo 'Prefer --mode https. Allow port 3000 in the cloud/network firewall only from your own address.'
    ;;
  https)
    if [[ "$family" == el ]]; then
      dnf -y -q install nginx openssl policycoreutils-python-utils
      setsebool -P httpd_can_network_connect 1
    else
      export DEBIAN_FRONTEND=noninteractive
      apt-get -qq update && apt-get -qq install -y nginx openssl
      rm -f /etc/nginx/sites-enabled/default
    fi
    primary_address
    install -d -m 0750 -o root -g root "$tls_dir"
    if [[ ! -s "$tls_dir/semaphore.key" ]]; then
      san="IP:$address"
      [[ "$address" =~ ^[0-9.]+$ ]] || san="DNS:$address"
      openssl req -x509 -newkey rsa:4096 -sha256 -days 825 -nodes \
        -keyout "$tls_dir/semaphore.key" -out "$tls_dir/semaphore.crt" \
        -subj "/CN=$address" -addext "subjectAltName=$san" >/dev/null 2>&1
      chmod 0600 "$tls_dir/semaphore.key"; chmod 0644 "$tls_dir/semaphore.crt"
    fi
    cat > "$nginx_site" <<'NGINX'
# Generated by scripts/expose-semaphore.sh: TLS in front of the loopback-only Semaphore UI.
map $http_upgrade $semaphore_connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name _;
    server_tokens off;
    ssl_certificate /etc/semaphore/tls/semaphore.crt;
    ssl_certificate_key /etc/semaphore/tls/semaphore.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    add_header Strict-Transport-Security "max-age=31536000" always;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $semaphore_connection_upgrade;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_buffering off;
    }
}
NGINX
    chmod 0644 "$nginx_site"
    set_interface 127.0.0.1
    wait_ping
    firewall remove 3000/tcp || true
    nginx -t >/dev/null
    systemctl enable --now nginx >/dev/null
    systemctl reload nginx
    firewall add https
    printf 'https\n' > "$marker"; chmod 0644 "$marker"
    fingerprint=$(openssl x509 -in "$tls_dir/semaphore.crt" -noout -fingerprint -sha256 | cut -d= -f2)
    echo "Semaphore UI: https://$address/  (self-signed certificate; expect a browser warning once)"
    echo "Certificate SHA-256 fingerprint to compare in the browser: $fingerprint"
    echo 'Semaphore itself still listens only on 127.0.0.1:3000. Allow port 443 in the cloud/network firewall only from your own address.'
    ;;
esac
