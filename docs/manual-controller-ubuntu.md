# Build the Ubuntu controller by hand

[Back to the guide](../README.md) · [The installer: Stage 1](stage-1-controller.md) · [Next: SSH and sudo by hand](manual-access.md)

**Most readers should use [Stage 1](stage-1-controller.md) instead.** Its
installer does everything on this page and more, in one reviewed run. This
page shows how the installer's work looks step by step, so you can learn what
each layer is and does. Use it on a separate VM, not on a controller you also
want to install with the installer.

**Where: a fresh Ubuntu 24.04 amd64 controller VM, built as in
[Stage 0](stage-0-plan.md), using your administrator account.** The controller
is separate from the managed targets. There is no by-hand page for Enterprise
Linux; [Stage 1](stage-1-controller.md#ubuntu-or-enterprise-linux-the-differences)
lists how its installer differs.

## Goal

Install Ansible, PostgreSQL and Semaphore with private application access and
locally generated credentials. The Ansible environment and the Semaphore binary
are pinned to the tested versions.

## What this path leaves out

The installer runs these six steps, then goes further: it creates the
service key `/etc/semaphore/svc_ansible`, the lab folder `/opt/ansible-lab`
and the seeded **Ansible Practice** project with its 22 task templates. This
page stops after the application is running. On this path you create your own
automation key and prepare the targets in [SSH and sudo by
hand](manual-access.md), then build the Semaphore project yourself in
[chapter 6](06-semaphore.md).

Do not follow this page and then run the installer on the same VM. The
installer refuses existing state; it is not an upgrade, password-reset or
recovery utility.

## Before you start

**Where: the controller.** Get the guide into the guide's folder, the same one
Stage 1 uses, and run every step below from it:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/kevo099/ansible-semaphore-guide.git ~/ansible-semaphore-guide
cd ~/ansible-semaphore-guide
```

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

Run from the guide's folder:

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv git curl tar \
  openssh-client postgresql-16 ca-certificates
sudo python3.12 -m venv /opt/ansible-venv
sudo /opt/ansible-venv/bin/pip install --requirement requirements-controller.txt
sudo chmod -R go+rX /opt/ansible-venv
/opt/ansible-venv/bin/ansible --version
```

The virtual environment receives ansible-core 2.21.4 with every Python
dependency pinned in
[`requirements-controller.txt`](../requirements-controller.txt), the set that
the September 2026 verification installed. Python 3.12 and PostgreSQL 16 come
from Ubuntu's repositories and follow its updates.

**Check:** the Ansible output reports core 2.21.4, jinja 3.1.6 and Python 3.12
from the virtual environment. The OS's default Python remains available for its
own utilities.

**Concept:** the controller Python runs Ansible itself. A target's Python runs
the transferred modules. Those are separate compatibility requirements.

## Manual step 3: create the service account and configuration

Run from the guide's folder:

```bash
sudo useradd --system --create-home --home-dir /var/lib/semaphore \
  --shell /usr/sbin/nologin semaphore
sudo install -d -o root -g semaphore -m 0750 /etc/semaphore
sudo install -d -o semaphore -g semaphore -m 0700 \
  /var/lib/semaphore /var/lib/semaphore/tmp
sudo python3 controller/controller_config.py --directory /etc/semaphore
sudo chown root:semaphore /etc/semaphore/config.json
sudo chmod 0640 /etc/semaphore/config.json
sudo install -o root -g semaphore -m 0640 /dev/null /etc/semaphore/known_hosts
sudo install -o root -g semaphore -m 0640 /dev/null /etc/semaphore/gitconfig
sudo tee -a /etc/semaphore/gitconfig >/dev/null <<'EOF'
[safe]
    directory = /opt/ansible-guide.git
EOF
```

The generator creates a unique database password, cookie keys, an access-key
encryption key and an initial administrator password. It refuses to overwrite
existing files and prints no credential values. The access-key encryption key
must be backed up with the database to recover Key Store credentials.

Git refuses to let the service read a repository owned by another account
unless the service's Git configuration lists it. The manual entry above
lists only the optional local repository in
[chapter 7](07-git-and-vscode.md#optional-a-reviewed-local-repository-on-the-controller).
The installer instead lists the lab folder selected by `--lab-dir`.
Appending with `tee -a` keeps the file's `root:semaphore` ownership.

**Check permissions without displaying configuration contents:**

```bash
sudo stat -c '%a %U:%G %n' /etc/semaphore /etc/semaphore/config.json \
  /etc/semaphore/initial-admin-password /etc/semaphore/known_hosts \
  /etc/semaphore/gitconfig
```

Expected: directory `750 root:semaphore`, configuration `640 root:semaphore`,
initial password `600 root:root`, known-hosts and Git configuration files
`640 root:semaphore`. The known-hosts file is initially empty, so target jobs
are not ready yet.

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
sudo python3 controller/create-database.py
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

From the guide's folder:

```bash
sudo -u semaphore /usr/local/bin/semaphore migrate --config /etc/semaphore/config.json
sudo python3 controller/create-admin.py
sudo install -o root -g root -m 0644 controller/templates/semaphore.service \
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

```bash
sudo python3 controller/check-controller.py
sudo systemctl status semaphore postgresql@16-main --no-pager
curl --fail http://127.0.0.1:3000/api/ping
```

Expect `"passed": true`, active services and `pong`. This proves application
readiness, not target access or a successful authenticated job. The targets
come next, in [SSH and sudo by hand](manual-access.md).

## Open the browser privately

**Where: your workstation.** Replace the login and controller address with your
own:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8088:127.0.0.1:3000 \
  ADMIN@CONTROLLER_ADDRESS
```

First verify the controller's SSH host key against its trusted console. Open
`http://127.0.0.1:8088/` in the workstation browser. The application connection
crosses the network inside SSH. Close the SSH session to close the tunnel.

Use the `admin` login and the password in the controller's root-only
`/etc/semaphore/initial-admin-password`. Read it in your own SSH session on the
controller:

```bash
sudo cat /etc/semaphore/initial-admin-password
```

Do not paste it into Git, chat, job variables or a screenshot. Change the UI
password and store the new value in your password manager. The initial password
file does not update automatically.

To reach the UI on the controller's own address instead of through a tunnel,
`controller/expose-semaphore.sh --mode https` works after this path too, as
[Stage 1](stage-1-controller.md#optional-publish-the-ui-on-the-controllers-address)
shows; `--mode loopback` takes the UI off the network again.

## Concept

Application readiness, browser access and target automation are three separate
checks. A working login page does not prove that Ansible can authenticate to a
host, run Python or use sudo.

## Next

Prepare the targets by hand: [SSH and sudo by hand](manual-access.md). To keep
this controller current later, see
[update a controller](controller-update.md); it applies only to controllers
the installer seeded.
