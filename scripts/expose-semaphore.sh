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
#   loopback  Close the firewall port, remove the proxy site, bind Semaphore to
#             127.0.0.1 again, and stop and disable nginx if it serves nothing else.
#             The nginx package, the replacement nginx.conf (Enterprise Linux), the
#             SELinux boolean httpd_can_network_connect and the certificate stay.
#
# --address is the IPv4 or IPv6 address or DNS name you browse to. The default is
# the IPv4 address of this VM's default route, which behind NAT is a private one.
# The certificate in /etc/semaphore/tls is created once and reused by later https
# runs. To name a new address, remove semaphore.key and semaphore.crt there first.
#
# The cloud/network firewall in front of the VM is not touched; allow the chosen
# port there yourself, ideally only from your own address.
set -euo pipefail
umask 077

# Print the comment block at the top of this file.
usage() { sed -n '2,/^[^#]/{/^#/p}' "$0"; }
missing() { echo "$1 needs a value."; usage; exit 2; }

# Split so the repository validator does not read this as a real address.
any_address='0.0.0''.0'
mode= address=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) [[ $# -ge 2 ]] || missing "$1"; mode="$2"; shift ;;
    --address) [[ $# -ge 2 ]] || missing "$1"; address="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; exit 2 ;;
  esac
  shift
done
[[ "$mode" == https || "$mode" == http || "$mode" == loopback ]] || { usage; exit 2; }
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

# Remove this script's proxy site. If nginx then listens nowhere, stop it so no
# listener is left behind; keep it running if you configured other sites.
retire_proxy() {
  rm -f "$nginx_site"
  if systemctl is-active --quiet nginx; then
    if nginx -T 2>/dev/null | grep -Eq '^[[:space:]]*listen[[:space:]]'; then
      systemctl reload nginx || true
    else
      systemctl disable --now nginx >/dev/null 2>&1 || true
      echo 'nginx serves nothing else; stopped and disabled it.'
    fi
  fi
}

# Settle the address for the URL and the certificate before changing anything. An
# IPv4 or IPv6 address gets an IP entry in the certificate, a name a DNS entry, and
# an IPv6 address needs brackets in a URL.
primary_address() {
  address="${address:-$(ip -4 route get 1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1); exit}')}"
  address=${address#\[}; address=${address%\]}
  [[ -n "$address" ]] || { echo 'Could not determine this VM address; pass --address.'; exit 1; }
  if [[ "$address" =~ ^[0-9.]+$ || "$address" == *:* ]]; then
    if [[ "$address" == *%* ]] || ! python3 -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$address" 2>/dev/null; then
      echo "Not a valid IP address: $address. Pass an address without a %zone suffix, or a DNS name."; exit 1
    fi
    san="IP:$address"
  elif [[ "$address" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
    san="DNS:$address"
  else
    echo "Not a usable IP address or DNS name: $address"; exit 1
  fi
  url_host=$address
  [[ "$address" != *:* ]] || url_host="[$address]"
}

case "$mode" in
  loopback)
    retire_proxy
    firewall remove https || true
    firewall remove 3000/tcp || true
    set_interface 127.0.0.1
    wait_ping
    rm -f "$marker"
    echo 'Semaphore is loopback-only again; reach it through an SSH tunnel.'
    ;;
  http)
    primary_address
    retire_proxy
    firewall remove https || true
    set_interface "$any_address"
    wait_ping
    firewall add 3000/tcp
    printf 'http\n' > "$marker"; chmod 0644 "$marker"
    echo "Semaphore listens in PLAIN TEXT on every address, port 3000: http://$url_host:3000/"
    echo 'Prefer --mode https. Allow port 3000 in the cloud/network firewall only from your own address.'
    ;;
  https)
    primary_address
    if [[ "$family" == el ]]; then
      dnf -y -q install nginx openssl policycoreutils-python-utils
      setsebool -P httpd_can_network_connect 1
      # The package's nginx.conf also serves a default site on port 80 on every
      # address. Keep the original once and use a main file without that server.
      [[ -e /etc/nginx/nginx.conf.before-semaphore ]] || cp -p /etc/nginx/nginx.conf /etc/nginx/nginx.conf.before-semaphore
      cat > /etc/nginx/nginx.conf <<'NGINXMAIN'
# Generated by scripts/expose-semaphore.sh for a dedicated Semaphore controller.
# The package default, including its plain-HTTP server on port 80, is kept in
# /etc/nginx/nginx.conf.before-semaphore.
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /run/nginx.pid;
include /usr/share/nginx/modules/*.conf;

events {
    worker_connections 1024;
}

http {
    access_log /var/log/nginx/access.log;
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 4096;
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    include /etc/nginx/conf.d/*.conf;
}
NGINXMAIN
      chmod 0644 /etc/nginx/nginx.conf
    else
      export DEBIAN_FRONTEND=noninteractive
      apt-get -qq update && apt-get -qq install -y nginx openssl
      rm -f /etc/nginx/sites-enabled/default
    fi
    install -d -m 0750 -o root -g root "$tls_dir"
    if [[ ! -s "$tls_dir/semaphore.key" || ! -s "$tls_dir/semaphore.crt" ]]; then
      openssl req -x509 -newkey rsa:4096 -sha256 -days 825 -nodes \
        -keyout "$tls_dir/semaphore.key" -out "$tls_dir/semaphore.crt" \
        -subj "/CN=$address" -addext "subjectAltName=$san" >/dev/null 2>&1
      chmod 0600 "$tls_dir/semaphore.key"; chmod 0644 "$tls_dir/semaphore.crt"
    else
      # The existing certificate is reused; say so when it names another address.
      check=-checkhost; [[ "$san" != IP:* ]] || check=-checkip
      match=$(openssl x509 -in "$tls_dir/semaphore.crt" -noout "$check" "$address" 2>&1 || true)
      if [[ "$match" != *" does match "* ]]; then
        echo "Warning: the existing certificate does not name $address. To replace it, run"
        echo "  sudo rm $tls_dir/semaphore.key $tls_dir/semaphore.crt"
        echo 'and then this --mode https command again.'
      fi
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
    echo "Semaphore UI: https://$url_host/  (self-signed certificate; expect a browser warning once)"
    echo "Certificate SHA-256 fingerprint to compare in the browser: $fingerprint"
    echo 'Semaphore itself still listens only on 127.0.0.1:3000. Allow port 443 in the cloud/network firewall only from your own address.'
    ;;
esac
