# 3. Install the native controller

[Previous: create VMs](02-create-vms.md) · [Next: SSH and sudo](04-access.md)

**Where: a fresh Ubuntu 24.04 amd64 controller VM, using your administrator
account.** The controller is separate from the two managed targets.

## Goal

Install Ansible, PostgreSQL and Semaphore with a reproducible runtime, private
application access and locally generated credentials.

## Choose one installation path

On RHEL, AlmaLinux or Rocky Linux 9, use the
[Enterprise Linux installer](03-controller-el9.md) instead; it also seeds a
local-folder practice project.

- **Manual path:** follow the numbered sections below to see what each layer does.
- **Installer path:** read the script, view its plan, then apply it on the fresh VM.

Both paths use the files in this repository. Do not execute the manual path
and then run the fresh installer over it. The installer intentionally refuses
existing state; it is not an upgrade, password-reset or recovery utility.

Start on the controller:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/kevo099/ansible-semaphore-guide.git
cd ansible-semaphore-guide
bash scripts/install-controller.sh --plan
```

For the installer path, read the script and its Python helpers first, then:

```bash
sudo bash scripts/install-controller.sh --apply
```

It changes this controller VM only. It does not create VMs, discover your
hypervisor, configure targets or schedule Ansible jobs. When it succeeds,
continue at **Check controller readiness** below.

## Manual step 1: inspect the fresh host

**Do:** verify the operating system, architecture and absence of earlier state.

```bash
cat /etc/os-release
dpkg --print-architecture
sudo python3 - <<'PY'
from pathlib import Path
paths = ['/etc/semaphore', '/opt/ansible-venv', '/var/lib/semaphore',
         '/etc/postgresql', '/usr/local/bin/semaphore',
         '/etc/systemd/system/semaphore.service']
existing = [p for p in paths if Path(p).exists() or Path(p).is_symlink()]
if existing:
    raise SystemExit('Existing installation state: ' + ', '.join(existing))
print('No existing controller state at the guide paths.')
PY
```

**Check:** Ubuntu reports `24.04`, architecture is `amd64`, and the fresh-state
check succeeds. If it fails, choose a new dedicated VM or use an appropriate
recovery/upgrade plan for the existing service.

**Concept:** installation paths and a database are owned resources. A learning
installer should not silently take over an existing application.

## Manual step 2: install the runtime

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv git curl tar \
  openssh-client postgresql-16 ca-certificates
sudo python3.12 -m venv /opt/ansible-venv
sudo /opt/ansible-venv/bin/pip install 'ansible-core==2.20.8'
sudo chmod -R go+rX /opt/ansible-venv
/opt/ansible-venv/bin/ansible --version
```

**Check:** the Ansible output reports core 2.20.8 and Python 3.12 from the virtual
environment. The OS's default Python remains available for its own utilities.

**Concept:** the controller Python runs Ansible itself. A target's Python runs
the transferred modules. Those are separate compatibility requirements.

## Manual step 3: create the service account and configuration

Run from the repository root:

```bash
sudo useradd --system --create-home --home-dir /var/lib/semaphore \
  --shell /usr/sbin/nologin semaphore
sudo install -d -o root -g semaphore -m 0750 /etc/semaphore
sudo install -d -o semaphore -g semaphore -m 0700 \
  /var/lib/semaphore /var/lib/semaphore/tmp
sudo python3 scripts/controller_config.py --directory /etc/semaphore
sudo chown root:semaphore /etc/semaphore/config.json
sudo chmod 0640 /etc/semaphore/config.json
sudo install -o root -g semaphore -m 0640 /dev/null /etc/semaphore/known_hosts
sudo install -o root -g semaphore -m 0640 /dev/null /etc/semaphore/gitconfig
```

The generator creates a unique database password, cookie keys, an access-key
encryption key and an initial administrator password. It refuses to overwrite
existing files and prints no credential values. The access-key encryption key
must be backed up with the database to recover Key Store credentials.

**Check permissions without displaying configuration contents:**

```bash
sudo stat -c '%a %U:%G %n' /etc/semaphore /etc/semaphore/config.json \
  /etc/semaphore/initial-admin-password /etc/semaphore/known_hosts
```

Expected: directory `750 root:semaphore`, configuration `640 root:semaphore`,
initial password `600 root:root`, known-hosts file `640 root:semaphore`.
The known-hosts file is initially empty, so target jobs are not ready yet.

**Concept:** the web application needs its own configuration and database
credential. It does not need your hypervisor, cloud administrator or everyday
workstation credentials.

## Manual step 4: configure PostgreSQL

```bash
sudo tee /etc/postgresql/16/main/conf.d/ansible-guide.conf >/dev/null <<'EOF'
listen_addresses = 'localhost'
password_encryption = 'scram-sha-256'
EOF
sudo chmod 0644 /etc/postgresql/16/main/conf.d/ansible-guide.conf
sudo python3 - <<'PY'
from pathlib import Path
p=Path('/etc/postgresql/16/main/pg_hba.conf')
p.write_text(
    '# Dedicated Semaphore TCP login\n'
    'host semaphore semaphore 127.0.0.1/32 scram-sha-256\n'
    'host semaphore semaphore ::1/128 scram-sha-256\n' + p.read_text()
)
PY
sudo systemctl enable --now postgresql postgresql@16-main
sudo systemctl restart postgresql@16-main
sudo python3 scripts/create-database.py
```

**Check:** the helper reports creation of the dedicated database and role.
It sends the locally generated database password over stdin and refuses an
existing role or database. Check the listener:

```bash
sudo -u postgres psql -X -Atc 'SHOW listen_addresses;'
sudo ss -lntp 'sport = :5432'
```

Expected: `localhost`, with TCP listeners only on `127.0.0.1` and optionally
`::1`. The database account belongs to Semaphore, not to a Linux login.

## Manual step 5: install the pinned Semaphore binary

```bash
mkdir -p ~/.cache/ansible-semaphore-guide
chmod 700 ~/.cache/ansible-semaphore-guide
curl --fail --location --retry 3 \
  --output ~/.cache/ansible-semaphore-guide/semaphore.tar.gz \
  https://github.com/semaphoreui/semaphore/releases/download/v2.19.12/semaphore_community_2.19.12_linux_amd64.tar.gz
printf '%s  %s\n' \
  2576f8a473c5e91bd0d7833976111c56f0ad43720210f9ca437037d10acd97cc \
  "$HOME/.cache/ansible-semaphore-guide/semaphore.tar.gz" | sha256sum --check
tar -xzf ~/.cache/ansible-semaphore-guide/semaphore.tar.gz \
  -C ~/.cache/ansible-semaphore-guide semaphore
sudo install -m 0755 ~/.cache/ansible-semaphore-guide/semaphore /usr/local/bin/semaphore
/usr/local/bin/semaphore version
```

**Check:** the checksum reports `OK` and the installed binary reports 2.19.12.
If the checksum differs, stop and inspect the download/release; do not replace
the expected checksum merely to make the command pass. The pin corresponds to
the [official Community release](https://github.com/semaphoreui/semaphore/releases/tag/v2.19.12).

## Manual step 6: initialize and start the application

From the repository root:

```bash
sudo -u semaphore /usr/local/bin/semaphore migrate --config /etc/semaphore/config.json
sudo python3 scripts/create-admin.py
sudo install -o root -g root -m 0644 templates/semaphore.service \
  /etc/systemd/system/semaphore.service
sudo systemctl daemon-reload
sudo systemctl enable --now semaphore
```

The admin helper reads the generated password from the protected local file.
This pinned CLI requires a password argument: the value briefly exists in the
child process's argument list, but is not stored in shell history or printed
by the helper. Perform bootstrap on the trusted, dedicated controller and do
not record its credential handling in a terminal transcript.

The service runs without root privileges and can write its runtime state under
`/var/lib/semaphore`. It cannot use local sudo to administer the controller.
Remote target privilege escalation is configured separately.

## Check controller readiness

For either installation path:

```bash
sudo python3 scripts/check-controller.py
sudo systemctl status semaphore postgresql@16-main --no-pager
curl --fail http://127.0.0.1:3000/api/ping
```

Expect `passed: true`, active services and HTTP success. This proves application
readiness, not target access or a successful authenticated job. Complete those
checks in the next guides.

## Open the browser privately

**Where: your workstation.** Replace the login and controller name with your own:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8088:127.0.0.1:3000 \
  YOUR_ADMIN@controller.example.test
```

First verify the controller's SSH host key against its trusted console. Open
`http://127.0.0.1:8088/` in the workstation browser. The application connection
crosses the network inside SSH. Close the SSH session to close the tunnel.

Use the `admin` login and the password in the controller's root-only
`/etc/semaphore/initial-admin-password`. Retrieve it through your own private
terminal or password-manager workflow; do not paste it into Git, chat, job
variables or a screenshot. Change the UI password and store the new value in
your password manager. The initial password file does not update automatically.

An optional loopback nginx configuration is provided in
[`templates/nginx-loopback.conf`](../templates/nginx-loopback.conf). It is not
needed for the direct SSH tunnel and is not installed by the script. If you
choose it, configure nginx on a dedicated controller, disable its default
public listener, validate with `nginx -t`, and forward to loopback port 8080.
Use the [official reverse-proxy guide](https://semaphoreui.com/docs/admin-guide/reverse-proxy/nginx)
for a separately designed HTTPS deployment.

## Concept

Application readiness, browser access and target automation are three separate
checks. A working login page does not prove that Ansible can authenticate to a
host, run Python or use sudo.
