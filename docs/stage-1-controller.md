# Stage 1: install the controller

[Back to the guide](../README.md) · [Previous: Stage 0, plan the lab](stage-0-plan.md) · Next: [Stage 2, existing machines](stage-2-existing-machines.md) or [Stage 3, new VMs with cloud-init](stage-3-new-vms-cloud-init.md)

## Goal

Turn the fresh controller VM from Stage 0 into a working controller in one
reviewed run: Ansible, PostgreSQL and Semaphore installed and pinned, and a
Semaphore project with 24 ready task templates that run the guide's playbooks
from a local folder on the controller. When this stage is done, you have
logged in to Semaphore through an SSH tunnel, changed the admin password, and
checked the copy of the service key, which every target will trust, that the
installer leaves in your home folder.

## Before you start

- The controller VM from [Stage 0](stage-0-plan.md): a fresh Ubuntu 24.04
  amd64 VM, or a fresh RHEL, AlmaLinux or Rocky Linux 9.4 or later x86_64 VM,
  with nothing else installed on it.
- An SSH login to it as your own administrator, who can use `sudo`.
- Outbound HTTPS from the controller to its package mirrors, PyPI and GitHub.
- On RHEL: the system registered with BaseOS and AppStream enabled. On an
  Enterprise Linux image older than 9.4: `sudo dnf -y upgrade`, then reboot.
- A snapshot of the clean VM, and your worksheet from Stage 0.

## Ubuntu or Enterprise Linux: the differences

One page covers both installers. They run the same steps from the same shared
code, `controller/controller-common.sh`, and seed the same practice project.
Where a command below differs, both forms are shown.

| | Ubuntu 24.04 | RHEL, AlmaLinux or Rocky Linux 9.4 or later |
| --- | --- | --- |
| Installer | `controller/install-controller.sh` | `controller/install-controller-el9.sh` |
| Architecture | amd64 | x86_64 |
| Install Git first | `sudo apt-get install -y git` | `sudo dnf install -y git` |
| PostgreSQL 16 from | Ubuntu's repositories | The AppStream `postgresql:16` module stream |
| PostgreSQL unit to check | `postgresql@16-main` | `postgresql` |
| PostgreSQL data | `/etc/postgresql/16/main`, `/var/lib/postgresql` | `/var/lib/pgsql/data` |
| Service unit installed from | `controller/templates/semaphore.service` | `controller/templates/semaphore-el9.service` |
| Installer's own wait for a busy package manager | Up to ten minutes for the dpkg lock; retries `apt-get update` every 10 seconds, up to 30 times | None |
| SELinux | Not used | Stays enforcing; labels restored by the installer |
| Host firewall opened by `--expose` | `ufw`, when active | `firewalld`, when active |

### Enterprise Linux differences worth knowing

- PostgreSQL comes from the `postgresql:16` module stream; the unit is
  `postgresql`, not `postgresql@16-main`, and the data directory is
  `/var/lib/pgsql/data`.
- [Chapter 10](10-recovery.md)'s capture also records
  `/var/lib/pgsql/data/postgresql.conf`, `pg_hba.conf` and `/opt/ansible-lab`;
  add your own folder to its list if you used `--lab-dir`. Its restore
  commands show Ubuntu paths; substitute the ones above.
- SELinux stays enforcing. The installer runs `restorecon` on the binary and
  the lab folder; do not set permissive mode to hide a labeling problem.
- Without `--expose`, the installer leaves `firewalld` untouched, and
  Semaphore and PostgreSQL listen only on loopback. `--expose https` (or
  `controller/expose-semaphore.sh --mode https`) adds the `https` service to an
  active `firewalld`, runs nginx on port 443 and sets the persistent SELinux
  boolean `httpd_can_network_connect` so nginx can reach Semaphore.
  `--expose http` instead opens `3000/tcp` and binds Semaphore to every
  address. `--mode loopback` closes the port again but leaves the boolean set;
  turn it off with `sudo setsebool -P httpd_can_network_connect 0` if nothing
  else on the VM needs it.
- On RHEL, the registration must enable BaseOS and AppStream at release 9.4
  or later; a cloud image whose provider's repository plugin serves them works
  the same way. A release lock or update stream held below 9.4 has neither
  `python3.12` nor `postgresql:16`. AlmaLinux and Rocky use their own mirrors.
- Kernel and package updates applied during `dnf install` may require a
  reboot before they are fully in effect; the installer does not reboot.

## Do: get the guide onto the controller

**Where: the controller, over SSH as your administrator.** Install Git. On
Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git
```

On RHEL, AlmaLinux or Rocky Linux:

```bash
sudo dnf install -y git
```

Then clone the guide into your home folder:

```bash
git clone https://github.com/kevo099/ansible-semaphore-guide.git ~/ansible-semaphore-guide
cd ~/ansible-semaphore-guide
```

On a machine that is already hardened to the DISA STIG, add `--template=`
after `git clone`, and expect the installer to stop once with four `fapolicyd`
rules to add; chapter 9,
[Harden the controller itself](09-security-benchmarks.md#harden-the-controller-itself),
explains both. Until those rules are loaded your account may not open the
guide's Python files, so read them in step 2 below with `sudo less`. On Ubuntu
hardened with `usg`, expect the installer to stop once over two files of the
SSH client instead; it prints the one command that ends that.

`~/ansible-semaphore-guide` is **the guide's folder**. Every command in this
guide that starts with `controller/` runs from it: the installer,
`onboard-target.sh`, `add-target.sh`, `lab-sudo.py`, `remove-target.sh`,
`expose-semaphore.sh`, `check-controller.py` and the update tool. It is not the
lab folder the installer creates; Semaphore never reads the guide's folder.

## Do: install with the installer

**Where: the controller, in the guide's folder, as your administrator.**

1. Print the plan. It changes nothing and needs no `sudo`. On Ubuntu:

   ```bash
   bash controller/install-controller.sh --plan
   ```

   On RHEL, AlmaLinux or Rocky Linux:

   ```bash
   bash controller/install-controller-el9.sh --plan
   ```

2. Read the plan, the installer, `controller/controller-common.sh` and the
   Python helpers it calls: `controller_config.py`, `create-database.py`,
   `create-admin.py`, `check-controller.py` and `seed-semaphore.py`. Reading
   the plan before `--apply` is the review step; the script does not replace
   it.

3. When you agree with the plan, apply it. On Ubuntu:

   ```bash
   sudo bash controller/install-controller.sh --apply
   ```

   On RHEL, AlmaLinux or Rocky Linux:

   ```bash
   sudo bash controller/install-controller-el9.sh --apply
   ```

Both installers take the same options, all optional:

| Option | Default | Meaning |
| --- | --- | --- |
| `--editor USER` | The account that ran `sudo` | Owner of the lab folder. Must be an existing account other than `root` and `semaphore`. Required when you run the installer from a root shell without `sudo`. |
| `--lab-dir DIR` | `/opt/ansible-lab` | Absolute path of the lab folder. Refused: `/`, and paths under `/home`, `/root`, `/run/user`, `/tmp`, `/var/tmp` and `/var/lib/semaphore`, which the hardened service cannot read. The nearest existing parent folder must let other accounts through, as `/opt` and `/srv` do. |
| `--expose https` or `--expose http` | None: the UI listens on loopback only | Also publish the UI on the controller's address; see [the optional section below](#optional-publish-the-ui-on-the-controllers-address). |
| `--address IP_OR_NAME` | The IPv4 address of the controller's default route | Only together with `--expose`: the address or DNS name you browse to, which the certificate and the printed URL name. |
| `--fapolicyd-ready` | The installer stops where `fapolicyd` is active without this guide's four rules | Skip that check, for a site that allowed the same paths another way; see chapter 9, [Harden the controller itself](09-security-benchmarks.md#harden-the-controller-itself). |

For example, a lab folder under `/srv` and HTTPS on the controller's address:

```bash
sudo bash controller/install-controller.sh --apply --lab-dir /srv/ansible-lab --expose https
```

Run the installer once, on a fresh VM. It refuses a VM that already has any of
`/etc/semaphore`, `/opt/ansible-venv`, `/usr/local/bin/semaphore`,
`/var/lib/semaphore`, `/etc/systemd/system/semaphore.service`, the lab folder,
PostgreSQL data, a `semaphore` command or a `semaphore` account. It is not an
upgrade, password-reset or recovery tool; to bring a controller to a newer
release of the guide, see [update a controller](controller-update.md). It
changes this controller VM only: it does not create VMs, discover your
hypervisor, configure targets or schedule jobs.

This guide uses the default `/opt/ansible-lab`. If you chose `--lab-dir DIR`,
use `DIR` wherever that path appears, and pass the same `--lab-dir DIR` to
`add-target.sh` and the update tool. Write the lab folder in your worksheet.

### What the installer creates

| Layer | Result |
| --- | --- |
| Runtime | Python 3.12, Git, `/opt/ansible-venv` with ansible-core 2.21.4 and every Python dependency pinned in [`requirements-controller.txt`](../requirements-controller.txt) |
| Database | PostgreSQL 16, loopback only, SCRAM login, with a dedicated `semaphore` role and database |
| Application | Semaphore Community 2.19.12, checksum-verified, `127.0.0.1:3000`, hardened `semaphore.service` run by the unprivileged `semaphore` account |
| Secrets | In `/etc/semaphore` (0750, root and the `semaphore` group): `config.json` (0640, readable by the service), the initial admin password and the `svc_ansible` RSA 4096 private key (both root-only), the service key `svc_ansible.pub` (0644), an empty `known_hosts` that `add-target.sh` fills, and `gitconfig`, which lets the service read the lab folder's Git history. No value is printed. |
| Lab folder | `/opt/ansible-lab`, owned by the editor and readable by the service: `ansible.cfg`, the nine playbooks and their supporting files, one STIG audit and apply playbook per system and version under `playbooks/stig/` (`rhel/9`, `almalinux/9`, `rocky/9`, `ubuntu/24.04`), the report summarizer `scripts/summarize_xccdf.py`, an empty `inventories/lab.ini`, a `content/` folder with the same per-system subfolders for SCAP files you supply, and a local Git history whose `.gitignore` keeps `inventories/`, `host_vars/` and `group_vars/` untracked |
| Semaphore objects | Project **Ansible Practice**; keys **None** and **Practice target SSH**; repository **Local lab folder**; inventory **Lab inventory file**; variable groups **Practice defaults**, **Allow required reboot**, **DISA SCAP file · RHEL 9** and **DISA SCAP file · Ubuntu 24.04**; seven template tabs, **Lessons**, **Patching**, **STIG · RHEL 9**, **STIG · AlmaLinux 9**, **STIG · Rocky Linux 9**, **STIG · Ubuntu 24.04** and **Operations** |
| 24 task templates | **Lessons:** Ping; Baseline preview; Baseline apply; Users; Webserver. **Patching:** Patch preview; Patch, no reboot; Patch, allow required reboot. **Each STIG tab**, with names that start with the system, such as **RHEL 9 · STIG audit**: STIG audit; STIG apply (approval required); STIG apply, allow required reboot; and on the RHEL 9 and Ubuntu 24.04 tabs, STIG audit, DISA SCAP file. **Operations:** Health report; Reboot one target |
| Key copy | `~/svc_ansible.pub` in the editor's home folder: a copy of the service key, owned by the editor, for the onboarding steps |

Every lesson template, and **Health report**, sets its **Ansible options →
Limit** to `lab`, the explicit limit the playbooks' preflight requires. Each STIG audit template sets
it to its system's inventory group, `enterprise_linux` or `ubuntu`, and skips
the hosts there that run another system, so **RHEL 9 · STIG audit** reports
only on RHEL 9 hosts. The STIG apply templates have no default limit: their
Run dialog asks for exactly one host and a recovery-point approval, and they
refuse a host that runs another system. **Reboot one target** has no default
limit either: its Run dialog asks for exactly one host and the choice
`REBOOT NOW - restart this one target`. The two preview templates add
`--check --diff` as CLI arguments. Only the templates whose names end in
“allow required reboot” receive `allow_reboot: true`. The patch template then
reboots only when the operating system reports that it needs one. Each **STIG
apply, allow required reboot** always reboots once after remediation, because
STIG changes such as kernel boot arguments and the crypto policy take full
effect only after a restart.

The STIG templates are optional. The audits change no security policy; the
apply templates do. Do not run them while learning the installation;
[chapter 9](09-security-benchmarks.md#the-seeded-stig-templates) describes them,
after the recovery preparation they depend on.

### The lab folder

Semaphore reads the **Local lab folder** straight from its working tree at
every run, uncommitted edits included; there is no clone step and nothing to
sync. Edit playbooks as the editor account. The folder's `.gitignore` keeps
`inventories/` out of Git, so Git cannot show or undo an inventory edit: copy
`lab.ini` aside before editing it by hand, and rely on
[chapter 10](10-recovery.md)'s capture of the lab folder for recovery.

The service reads the folder through the `semaphore` group, which your account
is deliberately not a member of, because that group can also read the
controller's secrets. New files and folders inherit the group from the setgid
folders, so create folders with plain `mkdir` rather than `mkdir -m` or
`install -d -m`, which can drop the setgid bit. Tools that write private files,
such as `ansible-vault create`, need a `chgrp semaphore` and `chmod 0640`
before Semaphore can read them.

## Check: controller readiness

**Where: the controller, in the guide's folder.** The installer's output ends
with three parts. First, the readiness report from `check-controller.py`:

```text
{
  "passed": true,
  "checks": {
    "semaphore_bind_matches_exposure_loopback": true,
    "configuration_is_private": true,
    "service_can_read_known_hosts": true,
    "service_can_start_ssh": true,
    "semaphore_is_active": true,
    "semaphore_is_enabled": true,
    "postgresql_is_active": true,
    "ansible_is_available": true,
    "strict_target_host_verification": true,
    "http_ping": true,
    "port_3000_listening": true,
    "port_3000_only_loopback": true,
    "port_5432_listening": true,
    "port_5432_only_loopback": true,
    "nginx_listens_only_where_expected": true
  }
}
```

Second, the seeding summary: the project **Ansible Practice** and its ID, the
repository path, the inventory file, the seven template tabs and 24
template names with their IDs:

```text
{
  "project": {
    "name": "Ansible Practice",
    "id": 1
  },
  "repository": {
    "name": "Local lab folder",
    "path": "/opt/ansible-lab"
  },
  "inventory": {
    "name": "Lab inventory file",
    "file": "/opt/ansible-lab/inventories/lab.ini"
  },
  "views": [
    "Lessons",
    ...
  ],
  "templates": {
    "Ping": 1,
    ...
  }
}
```

Third, the installer's closing lines, with your own account and lab folder:

```text
Controller installed and seeded. Next: prepare each target and add it with its verified
host key. For a machine that already exists, as your administrator in this folder:
  bash controller/onboard-target.sh ADMIN@ADDRESS
README.md lists the other ways, and cloud-init for new VMs.
Automation public key: /etc/semaphore/svc_ansible.pub (a copy is in HOME_FOLDER/svc_ansible.pub)
Local lab folder (edit as ADMIN): /opt/ansible-lab
The initial admin password is in /etc/semaphore/initial-admin-password (root only).
```

`HOME_FOLDER` is your account's home folder, such as the one `echo ~` prints.
With `--lab-dir DIR`, the `onboard-target.sh` line ends with `--lab-dir DIR`.
The text in parentheses is missing only when the installer could not write
the copy.

With `--expose https` or `--expose http`, the exposure lines described
[below](#optional-publish-the-ui-on-the-controllers-address) follow the
seeding summary, and a second readiness report follows them; that report names
the mode and adds its own checks. Both come before the closing lines.

Run the readiness check again at any time; it reads state and changes nothing:

```bash
cd ~/ansible-semaphore-guide
sudo python3.12 controller/check-controller.py
```

It exits with status 0 and `"passed": true` when every check passes, and with
status 1 when any check is `false`. Then confirm the services and listeners.
On Ubuntu:

```bash
sudo systemctl is-active semaphore postgresql@16-main
```

On RHEL, AlmaLinux or Rocky Linux:

```bash
sudo systemctl is-active semaphore postgresql
```

On either:

```bash
sudo ss -lntp | grep -E ':(3000|5432) '
curl --fail http://127.0.0.1:3000/api/ping
```

Both units print `active`, ports 3000 and 5432 are bound to `127.0.0.1` (and
5432 possibly to `[::1]`) only, and the ping prints `pong`. This proves
application readiness, not target access or a successful job; those come in
Stage 4.

## Do: open Semaphore

**Where: your workstation.** Open a tunnel to the controller, and keep this
session open while you use the UI:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8088:127.0.0.1:3000 \
  ADMIN@CONTROLLER_ADDRESS
```

If this workstation has not logged in to the controller before, compare the
host-key fingerprint it shows with the one in your worksheet first. The command
prints nothing while the tunnel is open. Browse to `http://127.0.0.1:8088/`. The
application connection crosses the network inside SSH; close the SSH session to
close the tunnel.

**Where: the controller, in a second SSH session as your administrator.** Read
the initial admin password:

```bash
sudo cat /etc/semaphore/initial-admin-password
```

The file is readable only by root. Log in as `admin` with that password. Copy
it straight into the login form or your password manager; do not paste it into
Git, chat, job variables or a screenshot.

Then change the `admin` password in the UI, and store the new one in your
password manager. The file keeps the initial password: it does not follow your
change, so from now on the password manager holds the real one. The update
tool will ask for the new password later, as
[update a controller](controller-update.md) describes.

**Check:** the **Ansible Practice** project is present with the objects listed
in [what the installer creates](#what-the-installer-creates), the **Task
Templates** page shows the **Lessons**, **Patching**, four **STIG ·** and
**Operations** tabs, the **Operations** tab holds **Health report** and
**Reboot one target**, and the Key Store shows the SSH key **Practice target SSH** by name only. Log
out and back in with the new password.

## Do: save the service key

**Where: the controller, as your administrator.** The installer created the
key pair Semaphore logs in to targets with: the private key stays in
`/etc/semaphore/svc_ansible` and in the Key Store as **Practice target SSH**,
and the public key, the service key, is `/etc/semaphore/svc_ansible.pub`. Every
target must trust that public key for the account `svc_ansible`. The installer
also left a copy in your home folder, where Stage 3 and the by-hand ways of
Stage 2 expect it; Stage 2's one command reads the original itself. Check that
the copy is there and matches:

```bash
cat ~/svc_ansible.pub
ssh-keygen -lf ~/svc_ansible.pub
sudo ssh-keygen -lf /etc/semaphore/svc_ansible.pub
```

The first prints one line that starts with `ssh-rsa` and ends with
`ansible-practice`; the other two print the same `SHA256:` value. If you
installed with `--editor USER`, the copy is in that account's home folder.

On a controller installed with an earlier release, or when the copy is
missing, make it:

```bash
sudo cat /etc/semaphore/svc_ansible.pub > ~/svc_ansible.pub
```

`/etc/semaphore` is readable only by root and the `semaphore` group, which your
account is deliberately not in, so reading it needs `sudo`.

It is a public key: copying it is safe, and you may also keep it in your
worksheet or on your workstation if you create targets from there in Stage 3.
Never copy the private key out of `/etc/semaphore`. Reinstalling the controller
creates a new key pair; then replace the old public key on each target with
the new one.

## Optional: publish the UI on the controller's address

**Where: the controller, in the guide's folder, as your administrator.** The
tunnel is the default and the recommended way in. If you would rather browse
to the controller directly, publish the UI behind nginx on port 443 with a
self-signed certificate. Pass `--expose https` to the installer, or, after it,
run:

```bash
sudo bash controller/expose-semaphore.sh --mode https
```

The certificate and the printed URL name the IPv4 address of the controller's
default route. On a LAN or a hypervisor bridge, such as a Proxmox lab network,
that is the controller's own address, the one you browse to, so the default is
right. Pass `--address` only when you browse to another name or address, for
example a DNS name:

```bash
sudo bash controller/expose-semaphore.sh --mode https --address controller.example.test
```

It prints the URL and the certificate's fingerprint:

```text
Semaphore UI: https://CONTROLLER_ADDRESS/  (self-signed certificate; expect a browser warning once)
Certificate SHA-256 fingerprint to compare in the browser: ...
Semaphore itself still listens only on 127.0.0.1:3000. Allow port 443 in the cloud/network firewall only from your own address.
```

Write both in your worksheet, and compare the fingerprint with the browser's
warning the first time. The script opens port 443 in `ufw` or `firewalld` when
one is active; a firewall in front of the VM, on the hypervisor or the
network, is yours to open, ideally only from your own address.
`--mode http` instead binds Semaphore itself to every address on port 3000 in
plain text; use it only on a network you fully control. `--mode loopback`
takes the UI off the network again. If only the exposure step of the installer
fails, the installer says so and prints the two commands to run once the cause
is fixed; do not run the installer again.

[Browser access](appendices/browser-access.md#https-on-the-vms-address)
describes the modes, the checks and [the return to
loopback](appendices/browser-access.md#return-to-loopback). On a cloud VM
behind NAT the default address is the private one; on Azure, see
[run the controller in Azure](platform-azure.md#optional-do-run-the-controller-in-azure).

## Save these values

| Value | Where it came from | Needed in |
| --- | --- | --- |
| The guide's folder, `~/ansible-semaphore-guide` | Your clone | Stages 2 to 4, updates |
| The lab folder, `/opt/ansible-lab` unless you chose `--lab-dir` | The installer's closing lines | Stage 4, updates |
| The initial admin password's location, `/etc/semaphore/initial-admin-password` | The installer's closing lines | First login only |
| Your changed Semaphore `admin` password | You, in the UI; keep it only in your password manager | Every login, updates |
| `~/svc_ansible.pub`, the copy of the service key | The installer, or `sudo cat /etc/semaphore/svc_ansible.pub` | Stage 3, and Stage 2's by-hand ways |
| The address you browse to, and the certificate fingerprint if you published the UI | `http://127.0.0.1:8088/` through the tunnel, or the exposure output | Every login |

## When it fails

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| `Requires Ubuntu 24.04.` or `Requires RHEL, AlmaLinux or Rocky Linux 9.4 or later.` | The other installer is the one for this VM | Run the installer for your operating system |
| `Requires Enterprise Linux 9.4 or later for python3.12 and the postgresql:16 stream` | The VM is at 9.3 or older | `sudo dnf -y upgrade`, reboot, run it again; register RHEL first |
| `Existing state: PATH. This installer runs only on a fresh VM` | Something is already installed, or an earlier run stopped part way | Return to the clean snapshot from Stage 0, or read [installer interrupted or failed](11-troubleshooting.md#installer-interrupted-or-failed) |
| `Pass --editor USER when not running through sudo.` | You ran it from a root shell | Run it with `sudo` as your administrator, or pass `--editor` |
| `The Semaphore service cannot read a lab folder at ...` | `--lab-dir` names a folder the service cannot see | Choose a path such as `/srv/ansible-lab` |
| `SHA-256 mismatch for ...` | A proxy or captive portal changed the download | Fix the network path and run `--apply` again; never edit the checksum |
| `apt-get update failed; another apt process may hold its lock. Retrying in 10 seconds.` | Unattended upgrades hold apt's lock on a new VM | Let it wait |
| The readiness report shows `"passed": false` | One named check failed | Look the check up in [controller checks](11-troubleshooting.md#controller-checks) |
| `Only the --expose MODE step failed. Do not run the installer again` | Only the optional exposure failed | Fix the cause shown above it, then run the two commands it prints |
| The tunnel command exits at once | Port 8088 is already in use on your workstation | Use another local port, such as `-L 127.0.0.1:8089:127.0.0.1:3000`, and browse to it |
| `Permission denied` reading a file under `/etc/semaphore` | Your account is not in the `semaphore` group, by design | Read it with `sudo` |

## Concept

The installer makes the same decisions that
[the by-hand Ubuntu walkthrough](manual-controller-ubuntu.md) shows one step at
a time, and refuses to make them twice. Application readiness, browser access
and target automation are three separate checks: a working login page does not
prove that Ansible can authenticate to a host, run Python or use sudo. Stage 4
proves those.

Later, when you need them:
[update the controller to a newer guide release](controller-update.md);
[the vendor STIG lessons](09-security-benchmarks.md#the-seeded-stig-templates);
[move the lab folder to a real Git repository](appendices/git-migration.md),
when tasks should run only reviewed, pushed code. The seeded Ubuntu installer,
its target addition, template runs and all three exposure modes were tested
live on Azure; see the [onboarding and STIG record](validation/2026-09-onboard-stig.md)
and [validation and limitations](VALIDATION.md).

## Next

Prepare each target:

- A machine that already exists: [Stage 2, onboard existing machines](stage-2-existing-machines.md),
  with the one command the closing lines name.
- A VM you are about to create: [Stage 3, new VMs with cloud-init](stage-3-new-vms-cloud-init.md).
