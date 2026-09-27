# Appendix: browser access

[Back to the guide](../../README.md) · [Ubuntu controller](../03-controller.md) · [Enterprise Linux controller](../03-controller-el9.md)

## Goal

Reach the Semaphore UI from your workstation without putting the application
itself on the network, and know how to publish it on the controller's address
and take it off again. This page applies to both installation paths.

## Private tunnel

This is the default and the recommended way in. Semaphore listens only on
`127.0.0.1:3000`, and your browser reaches it through SSH.

**Where: your workstation.** Replace the login and controller name with your
own, and keep the session open while you use the UI:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8088:127.0.0.1:3000 \
  YOUR_ADMIN@controller.example.test
```

Verify the controller's SSH host key against its trusted console the first
time. Then open `http://127.0.0.1:8088/`. The application connection crosses
the network inside SSH. Close the SSH session to close the tunnel.

The first login is `admin` with the password in the controller's root-only
`/etc/semaphore/initial-admin-password`. Read it through your own private
terminal, for example `sudo cat` in an SSH session, or a password-manager
workflow. Do not paste it into Git, chat, job variables or a screenshot.
Change the UI password after the first login and store the new value in your
password manager; the initial password file does not update itself.

**Check:** you can log out and back in, and `ss -lnt` on the controller still
shows port 3000 bound to `127.0.0.1` only.

## HTTPS on the VM's address

Use this when the VM sits on its own, with no VPN or jump host, and you want
to browse to its address. **Where: the controller, from the repository root.**

```bash
sudo bash scripts/expose-semaphore.sh --mode https
```

The script works on both installation paths. The Enterprise Linux installer
can also do it in the same run with `--expose https`; the Ubuntu installer has
no such option.

It installs nginx with a locally generated self-signed certificate on port
443, proxies to the still loopback-only Semaphore, opens 443 in the host
firewall (`ufw` on Ubuntu when it is active, `firewalld` on Enterprise Linux)
and prints the certificate's SHA-256 fingerprint. Compare that fingerprint
with the browser's warning the first time, then continue to
`https://VM_ADDRESS/`.

The distribution's nginx package also serves a test page on port 80. On
Ubuntu the script removes the package's default site. On Enterprise Linux it
keeps the package's `nginx.conf` as `/etc/nginx/nginx.conf.before-semaphore`
and installs a main file without that server, and it sets the persistent
SELinux boolean `httpd_can_network_connect` so nginx can reach Semaphore.

The certificate and the printed URL name the address the VM uses for its
default route. On a cloud VM behind NAT, that is the private address. There,
run the script yourself with `--address` and the public IP address or DNS name
you browse to; the installer's `--expose` cannot pass one. The certificate is
created only once, so to give it a new address later, remove it first:

```bash
sudo rm /etc/semaphore/tls/semaphore.key /etc/semaphore/tls/semaphore.crt
sudo bash scripts/expose-semaphore.sh --mode https \
  --address controller.example.test
```

`--mode http` instead binds Semaphore itself to every address on port 3000 in
plain text. Use it only on a network you fully control.

**Check:** from another machine, `curl -k https://VM_ADDRESS/api/ping` prints
`pong`, while `curl http://VM_ADDRESS:3000/` and `curl http://VM_ADDRESS/`
cannot connect. `sudo python3 scripts/check-controller.py` reports the
exposure it found and fails if nginx listens anywhere other than 443.

**Concept:** the script changes the host, not the cloud. Allow port 443 in the
VM's network security group or equivalent only from your own address. An admin
login page open to the internet is the mistake this design avoids.

For a separately designed HTTPS deployment with your own certificate
authority, read the [official reverse-proxy
guide](https://semaphoreui.com/docs/admin-guide/reverse-proxy/nginx). An
optional loopback-only nginx example is in
[`templates/nginx-loopback.conf`](../../templates/nginx-loopback.conf); it is
not needed for the tunnel and no script installs it.

## Return to loopback

```bash
sudo bash scripts/expose-semaphore.sh --mode loopback
```

This closes the firewall port, removes the proxy site, binds Semaphore to
`127.0.0.1` again, and stops and disables nginx when it serves nothing else.
Switching from https to http retires nginx the same way. It leaves the nginx
package, the replacement `nginx.conf` on Enterprise Linux, the SELinux boolean
and the certificate in `/etc/semaphore/tls`, which a later `--mode https`
reuses. Turn the boolean off with
`sudo setsebool -P httpd_can_network_connect 0` if nothing else on the VM
needs it.

**Check:** `sudo ss -lntp | grep -E ':(80|443|3000) '` shows only
`127.0.0.1:3000`, and the readiness check passes.

## Concept

Application readiness, browser access and target automation are separate
checks. The tunnel keeps the only network-facing service SSH, which you
already harden and monitor. Publishing the UI adds a TLS endpoint that you now
own: its certificate, its firewall rule and its exposure.
