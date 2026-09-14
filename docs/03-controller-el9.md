# 3b. Install a seeded controller on Enterprise Linux 9

[Previous: controller on Ubuntu](03-controller.md) · [Next: SSH and sudo](04-access.md)

**Where: a fresh RHEL 9, AlmaLinux 9 or Rocky Linux 9 x86_64 VM, using your
administrator account.** This is the Enterprise Linux alternative to the
Ubuntu installer. It goes one step further: after installing, it seeds
Semaphore with a practice project whose playbooks live in a **local folder on
the controller**, so you can run the first lessons before choosing a Git host.

## Goal

Get from a fresh VM to a Semaphore project with eight scoped task templates in
one reviewed run, and understand what the installer decided for you.

## What the installer creates

| Layer | Result |
| --- | --- |
| Runtime | Python 3.12, Git, `/opt/ansible-venv` with ansible-core 2.20.8 |
| Database | PostgreSQL 16 from the AppStream module stream, loopback only, SCRAM login |
| Application | Semaphore Community 2.19.12, checksum-verified, `127.0.0.1:3000`, hardened `semaphore.service` |
| Secrets | `/etc/semaphore/config.json`, initial admin password, `svc_ansible` RSA 4096 key pair; all root-only, never printed |
| Lab folder | `/opt/ansible-lab` owned by you, readable by the service: `ansible.cfg`, the five playbooks, an empty `inventories/lab.ini`, a local Git history |
| Semaphore objects | Project **Ansible Practice**; keys **None** and **Practice target SSH**; repository **Local lab folder**; inventory **Lab inventory file**; variable groups **Practice defaults** and **Allow required reboot**; templates Ping, Baseline preview, Baseline apply, Users, Webserver, Patch preview, Patch no reboot, Patch allow required reboot |

Every template passes `--limit lab` in its CLI arguments, because the
playbooks' preflight requires an explicit limit and this release does not turn
the template's separate limit field into one. The two preview templates add
`--check --diff`. Only the last patch template receives `allow_reboot: true`.

## Do: plan, read, apply

```bash
sudo dnf install -y git
git clone https://github.com/kevo099/ansible-semaphore-guide.git
cd ansible-semaphore-guide
bash scripts/install-controller-el9.sh --plan
```

Read the script and its helpers. When you agree with the plan:

```bash
sudo bash scripts/install-controller-el9.sh --apply
```

The lab folder is owned by the account that ran `sudo`; pass `--editor USER`
to choose another administrator, and `--lab-dir DIR` for a different absolute
path. The installer refuses a VM that already has Semaphore, PostgreSQL data,
the virtual environment or the lab folder. It is not an upgrade tool.

**Check:** the run ends with the readiness JSON from `check-controller.py`
reporting `"passed": true`, followed by the seeding summary naming the project,
the inventory file and eight template identifiers. Then:

```bash
sudo systemctl is-active postgresql semaphore
sudo ss -lntp | grep -E ':(3000|5432) '
sudo cat /etc/semaphore/svc_ansible.pub
```

Both services are active, both ports are bound to loopback only, and the
public key is the one you will authorize on each target.

**Concept:** the installer makes the same decisions the manual chapter walks
through, and refuses to make them twice. Reading the plan before `--apply` is
the review step; the script does not replace it.

## Do: open the UI privately

Same as the Ubuntu path. On your workstation:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8088:127.0.0.1:3000 \
  YOUR_ADMIN@controller.example.test
```

Browse to `http://127.0.0.1:8088/`, log in as `admin` with the password from
`/etc/semaphore/initial-admin-password`, read privately on the controller with
`sudo cat`. Change it after the first login.

**Check:** the **Ansible Practice** project is present with the objects listed
above. The Key Store shows the SSH key by name only.

## Do: add a target without leaving the terminal

The inventory Semaphore reads is a file: `/opt/ansible-lab/inventories/lab.ini`.
Editing it changes the next run's targets. The helper below adds a host and
its **verified** host key in one step. First read the fingerprint from the
target's trusted console:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Then on the controller:

```bash
sudo bash scripts/add-target.sh --name lab-alma --address alma.example.test \
  --group enterprise_linux --fingerprint 'SHA256:REPLACE_WITH_CONSOLE_VALUE'
```

The helper scans the address, keeps only the key whose fingerprint matches
what you typed, appends it to `/etc/semaphore/known_hosts`, and inserts the
host under the chosen group. A mismatch changes nothing and prints the
scanned fingerprints so you can investigate.

Authorize the automation key on the target for `svc_ansible` as described in
[the access chapter](04-access.md), using `/etc/semaphore/svc_ansible.pub`
instead of a key generated in your home directory.

**Check:** run the **Ping** template. The task log shows no clone step, the
inventory file path, and one host answering with its distribution.

**Concept:** a file inventory tied to a local repository is read at run time.
There is nothing to sync and nothing cached; the file is the truth. The trade
is that a half-edited file is also the truth, which is the reason the Git
chapter exists.

## Do: move to a real repository later

The lab folder already has a Git history. When you are ready:

```bash
cd /opt/ansible-lab
git remote add origin YOUR_REPOSITORY_URL
git push -u origin main
```

Then add a second Semaphore repository object pointing at that URL with its
own read-only credential, and switch one template at a time. The inventory,
keys and variable groups stay as they are.

## Enterprise Linux differences worth knowing

- PostgreSQL comes from the `postgresql:16` module stream; the unit is
  `postgresql`, not `postgresql@16-main`, and the data directory is
  `/var/lib/pgsql/data`.
- SELinux stays enforcing. The installer runs `restorecon` on the binary and
  the lab folder; do not set permissive mode to hide a labeling problem.
- `firewalld` is left untouched. Nothing listens beyond loopback.
- On RHEL, package installation needs working repositories: a registered
  system or a cloud image with a repository plugin. AlmaLinux and Rocky use
  their own mirrors.
- Kernel and package updates applied during `dnf install` may require a
  reboot before they are fully in effect; the installer does not reboot.

See [validation and limitations](VALIDATION.md) for what this path has and
has not been exercised against.
