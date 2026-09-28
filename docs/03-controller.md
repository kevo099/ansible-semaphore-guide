# 3. Install the native controller

[Previous: create VMs](02-create-vms.md) · [Next: SSH and sudo](04-access.md)

**Where: a fresh Ubuntu 24.04 amd64 controller VM, using your administrator
account.** The controller is separate from the two managed targets.

## Goal

Install Ansible, PostgreSQL and Semaphore with private application access and
locally generated credentials. The Ansible environment and the Semaphore binary
are pinned to the tested versions. The installer also creates a practice project
that runs the local playbooks, including the STIG lessons, without a Git remote.

## Choose one installation path

On RHEL, AlmaLinux or Rocky Linux 9.4 or later, use the
[Enterprise Linux installer](03-controller-el9.md) instead; both installers
seed the same local-folder practice project.

- **Manual path:** follow the numbered sections below to see what each layer does.
- **Installer path:** read the script, view its plan, then apply it on the fresh VM
  to get the stack and twelve ready-configured task templates.

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
continue at [Check controller readiness](#check-controller-readiness), then
[add targets and run the first lesson](#installer-path-add-targets-and-run-the-first-lesson).

## What the installer creates

| Layer | Result |
| --- | --- |
| Runtime | Python 3.12, Git and `/opt/ansible-venv` with ansible-core 2.21.4 and the pinned dependencies |
| Database | PostgreSQL 16 from Ubuntu's repositories, loopback only, SCRAM login |
| Application | Semaphore Community 2.19.12, checksum-verified, `127.0.0.1:3000`, hardened `semaphore.service` |
| Secrets | Protected files in `/etc/semaphore`: application configuration, the root-only initial admin password and `svc_ansible` RSA 4096 private key, plus its public key; no secret values are printed |
| Lab folder | `/opt/ansible-lab`, owned by the editor and readable by the service: `ansible.cfg`, seven playbooks and their supporting files, the report summarizer, an empty `inventories/lab.ini`, an empty `content/` folder for SCAP files you supply, and local Git history; `.gitignore` excludes inventories and host/group variables |
| Semaphore objects | Project **Ansible Practice**; keys **None** and **Practice target SSH**; repository **Local lab folder**; inventory **Lab inventory file**; variable groups **Practice defaults**, **Allow required reboot** and **Local SCAP content**; template tabs **Lessons**, **Patching** and **STIG** |
| Twelve task templates | **Ping**; **Baseline preview**; **Baseline apply**; **Users**; **Webserver**; **Patch preview**; **Patch, no reboot**; **Patch, allow required reboot**; **STIG audit (vendor scan only)**; **STIG apply (vendor fixes, approval required)**; **STIG apply, allow required reboot**; **STIG audit, local SCAP content** |

The lesson templates limit runs to the `lab` group. The two STIG apply
templates instead ask for exactly one host and a recovery-point approval when
you run them, and the local SCAP content template asks for the hosts its
content file is written for. The preview templates use `--check --diff`. Only the templates
named “allow required reboot” enable reboots. The four optional STIG templates
run the playbooks from this local folder; see
[the seeded STIG lessons](09-security-benchmarks.md#the-seeded-stig-templates)
for vendor-content prerequisites and the recovery preparation required before
remediation.

The folder belongs to the account that ran `sudo`. Use `--editor USER` to
choose another existing administrator, or specify it when invoking the
installer directly as root. Use `--lab-dir DIR` to choose a different absolute
path, such as `/srv/ansible-lab`. The installer refuses `/` and paths under
`/home`, `/root`, `/run/user`, `/tmp`, `/var/tmp` or `/var/lib/semaphore`, which
the hardened service cannot read. Parent folders must permit traversal by the
service. The installer checks access to the inventory before seeding.

For example, after reviewing the plan:

```bash
sudo bash scripts/install-controller.sh --apply --editor "$USER" \
  --lab-dir /srv/ansible-lab --expose https
```

Choose this command **or** the earlier default apply command, once on a fresh
VM. Existing controller state or an existing lab folder is refused. With
`--expose https`, the installer uses the shared exposure helper to publish nginx
on port 443 with a self-signed certificate. `--expose http` publishes plain HTTP
on port 3000. Without either option, application access stays on loopback. See
[browser access](appendices/browser-access.md#https-on-the-vms-address) for the
firewall checks and how to return to loopback.

This chapter uses `/opt/ansible-lab` below. If you choose another folder, use
that path and pass the same `--lab-dir DIR` to `scripts/add-target.sh`.

The seeded Ubuntu installer, its target addition, template runs and all three
exposure modes were tested live on Azure; see the
[onboarding and STIG record](validation/2026-09-onboard-stig.md).

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

Run from the repository root:

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
readiness, not target access or a successful authenticated job. The installer
also prints a seeding summary naming the project, inventory file and twelve
template identifiers. Complete the target checks below for the installer path,
or in [chapter 4](04-access.md) for the manual path.

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

To reach the UI on the controller's own address instead of through a tunnel,
see [browser access](appendices/browser-access.md#https-on-the-vms-address):
`scripts/expose-semaphore.sh --mode https` works after either installation
path, the installer also accepts `--expose https`, and `--mode loopback` takes
the UI off the network again.

## Installer path: add targets and run the first lesson

The **Ansible Practice** project already exists. Its inventory is the local
file `/opt/ansible-lab/inventories/lab.ini`, initially empty. Do not recreate
the project or configure a Git host to run these templates.

Prepare each target's `svc_ansible` account, sudo rule and SSH drop-in using
steps 2 to 4 of [chapter 4](04-access.md). In step 3, authorize the installer's
public key, `/etc/semaphore/svc_ansible.pub`. Copy it out on the controller
first, since your administrator account is deliberately not in the group that
can read `/etc/semaphore`:

```bash
sudo cat /etc/semaphore/svc_ansible.pub > ~/svc_ansible.pub
scp ~/svc_ansible.pub YOUR_ADMIN@ubuntu.example.test:ansible_lab.pub
```

Chapter 4's key-install command uses that destination name. If you also use
the chapter's separate terminal key, authorize both public keys on the target;
the chapter 3b [target setup](03-controller-el9.md#do-add-a-target-without-leaving-the-terminal)
shows how. Keep the installer's private key in its protected file and Key Store.

On each target's trusted console, read its RSA host-key fingerprint:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub
```

Then run the helper from the guide checkout on the controller, substituting
that target's address and fingerprint:

```bash
sudo bash scripts/add-target.sh --name lab-ubuntu --address ubuntu.example.test \
  --group ubuntu --fingerprint 'SHA256:REPLACE_WITH_CONSOLE_VALUE'
```

Use `--group enterprise_linux` for an EL9 target and include `--lab-dir DIR`
if you chose a custom folder. The helper adds the inventory entry and its
verified key to `/etc/semaphore/known_hosts`. A fingerprint mismatch or a
duplicate host is refused without changing either file. Skip chapter 4's step
6 on this path: it replaces the known-hosts file the helper maintains. RSA host
keys also support the EL9 vendor STIG's later crypto-policy change.

In Semaphore, run **Ping**. Expect every added target to report its
distribution, no failed hosts, and job paths under the lab folder without a
Git clone step. Before running **Baseline preview** or any other template
using sudo, add the target sudo credential using
[the seeded project's sudo setup](03-controller-el9.md#do-give-the-templates-the-targets-sudo-password).
That section covers one shared lab sudo password or encrypted per-target
passwords, including the service's file permissions. Then run **Baseline
preview**, inspect it, run **Baseline apply** and repeat the apply to check for
`changed=0`. Continue with [the lesson checks](06-semaphore.md#step-7-qualify-a-complete-job).

The service reads the current folder contents, including uncommitted edits.
Back up the inventory before editing it: Git ignores it. Edit playbooks as the
selected editor account and retain the service's read permissions. To move to
a real Git repository later, follow
[chapter 3b's migration section](03-controller-el9.md#do-move-to-a-real-repository-later).
It explains code promotion and why the inventory stays bound to the local
folder.

## Update a controller to a newer guide release

**Where: the controller, as its administrator.** A controller whose installer
seeded the practice project can take a newer release of the guide without being
reinstalled: any Enterprise Linux controller, and an Ubuntu controller installed
from release `v1.5.0` on. An Ubuntu controller from an earlier release has no
seeded project, so the script refuses it; build its project by hand as
[chapter 6](06-semaphore.md) describes. The installers refuse to run a second
time, so use [`scripts/update-controller.sh`](../scripts/update-controller.sh)
instead of installing again. Get the newer copy of the guide first; replace
`v1.6.0` with the release you want:

```bash
git clone --branch v1.6.0 https://github.com/kevo099/ansible-semaphore-guide.git ~/guide-new
cd ~/guide-new
sudo bash scripts/update-controller.sh
```

Without options it only shows its plan. For each guide file in the lab folder
(`playbooks/`, `ansible.cfg` and the report summarizer) it compares three
versions: yours, the guide's version you last installed, and the new one.

- A file only the new release changed is updated, and a file it no longer
  ships is removed if you never changed it.
- A file only you changed is kept as it is.
- Anything both changed stops the update: a file you and the release both
  changed, a file you changed that the release removes, or a file of yours at a
  path the release now uses. Compare them and decide; `--replace-edited` takes
  the release's version, and the folder's Git history keeps yours.
- Other files you added are never touched.

The plan also lists whether `content/` would be created for SCAP files you
supply, and the Semaphore variable groups, template tabs and templates it would
add, with the seeded templates it would put on a tab. When the plan is what you
expect, apply it:

```bash
sudo bash scripts/update-controller.sh --apply
```

It changes nothing when the lab folder has staged changes, uncommitted changes
to guide files, a link where a guide file or folder belongs, files that both
changed, or no `.guide-files.json` after an earlier update; it then says how to
restore that file from Git, or how to apply a reverted update again. It also
refuses to run twice at once.

It then logs in to Semaphore and checks the project before changing anything.
Only templates bound to the lab folder's repository and inventory count as
seeded, so a template of yours with the same name is left alone. In Semaphore it
only adds what the project lacks, and puts a seeded template that has no tab on
its tab. Before that it saves every template to a root-only file under
`/root/ansible-lab-update/`, and it confirms each template it edits, putting it
back if Semaphore changed any other setting. If it cannot confirm an edit, it
leaves a `pending-template-ID.json` record there, and later runs stop until you
have checked that template in the UI and deleted the record. It never changes
Semaphore itself, the database, Ansible, the inventory, keys, a template's
variable groups, or a tab you chose.

Last, it checks that the lab folder is exactly as planned; if you edited a
guide file meanwhile, it stops without touching the folder, and a second run
picks up from there. If you save a file in the very moment it is replaced, the
swap is undone, your version stays, and the update stops. It writes the files
as the lab folder's owner, so the `semaphore` group can still read them,
restores SELinux labels on Enterprise Linux, and commits them in the folder's
Git history with `.guide-files.json`, the record of the guide's own versions
that the next update compares with. `git revert HEAD` in the folder undoes that
commit; to apply the update again later, revert the revert. It finishes with
the readiness check, and a second run reports nothing to do. With a different
lab folder, add the same `--lab-dir DIR` the installer used. If several projects
share the seeded project's name, pass `--project-id` with its ID.

If you changed the administrator's password in the UI, the stored installer
password no longer works, and it asks for a Semaphore administrator's login and
password at the terminal. For an unattended run, create an API token as
[chapter 17](17-api-and-integrations.md#do-inspect-swagger-and-token-access)
shows and pass it as `SEMAPHORE_API_TOKEN` with
`sudo --preserve-env=SEMAPHORE_API_TOKEN`.

**Check:** the **Task Templates** page shows the tabs **Lessons**, **Patching**
and **STIG** beside **All**, and **Ping** still succeeds.

## Concept

Application readiness, browser access and target automation are three separate
checks. A working login page does not prove that Ansible can authenticate to a
host, run Python or use sudo.
