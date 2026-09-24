# 3b. Install a seeded controller on Enterprise Linux 9

[Previous: controller on Ubuntu](03-controller.md) · [Next: SSH and sudo](04-access.md)

**Where: a fresh RHEL 9, AlmaLinux 9 or Rocky Linux 9 x86_64 VM, using your
administrator account.** This is the Enterprise Linux alternative to the
Ubuntu installer. It goes one step further: after installing, it seeds
Semaphore with a practice project whose playbooks live in a **local folder on
the controller**, so you can run the first lessons before choosing a Git host.

## Goal

Get from a fresh VM to a Semaphore project with eleven scoped task templates in
one reviewed run, and understand what the installer decided for you.

## What the installer creates

| Layer | Result |
| --- | --- |
| Runtime | Python 3.12, Git, `/opt/ansible-venv` with ansible-core 2.20.8 |
| Database | PostgreSQL 16 from the AppStream module stream, loopback only, SCRAM login |
| Application | Semaphore Community 2.19.12, checksum-verified, `127.0.0.1:3000`, hardened `semaphore.service` |
| Secrets | `/etc/semaphore/config.json`, initial admin password, `svc_ansible` RSA 4096 key pair; all root-only, never printed |
| Lab folder | `/opt/ansible-lab` owned by you, readable by the service: `ansible.cfg`, the seven playbooks, the report summarizer, an empty `inventories/lab.ini`, a local Git history |
| Semaphore objects | Project **Ansible Practice**; keys **None** and **Practice target SSH**; repository **Local lab folder**; inventory **Lab inventory file**; variable groups **Practice defaults** and **Allow required reboot**; eleven templates: Ping, Baseline preview, Baseline apply, Users, Webserver, Patch preview, Patch no reboot, Patch allow required reboot, STIG audit, STIG apply, STIG apply allow reboot |

Every lesson template sets its **Ansible options → Limit** to `lab`, the
explicit limit the playbooks' preflight requires. The two STIG apply templates
have no default limit: their Run dialog asks for exactly one host. The two
preview templates add `--check --diff` as CLI arguments. Only the templates
whose names end in “allow required reboot” receive `allow_reboot: true`.

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
the inventory file and eleven template identifiers. Then:

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

## Do: reach the UI on the VM's address instead of a tunnel

The default keeps Semaphore on loopback for SSH tunnels. When the VM sits on
its own, with no VPN or jump host, publish the UI on its address:

```bash
sudo bash scripts/expose-semaphore.sh --mode https
```

Or pass `--expose https` to the installer to do it in the same run. This
installs nginx with a locally generated self-signed certificate on port 443,
proxies to the still loopback-only Semaphore, opens 443 in the host firewall
and prints the certificate's SHA-256 fingerprint. Compare that fingerprint
with the browser's warning the first time, then continue to
`https://VM_ADDRESS/`. `--mode http` instead binds Semaphore itself to every
address on port 3000 in plain text; use it only on a network you fully
control. `--mode loopback` reverts either choice.

**Check:** from another machine, `curl -k https://VM_ADDRESS/api/ping` prints
`pong`, while `curl http://VM_ADDRESS:3000/` is refused. `check-controller.py`
reports the exposure it found.

**Concept:** the script changes the host, not the cloud. Allow port 443 in the
VM's network security group or equivalent only from your own address; an
admin login page open to the internet is the mistake this design avoids.

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

**Check:** run the **Ping** template. The task log shows no clone step, its
paths are under `/opt/ansible-lab`, and each host answers with its
distribution.

**Concept:** a file inventory tied to a local repository is read at run time.
There is nothing to sync and nothing cached; the file is the truth. The trade
is that a half-edited file is also the truth, which is the reason the Git
chapter exists.

## Do: give the templates the targets' sudo password

The access chapter gives `svc_ansible` password-backed sudo. The seeded
inventory has no sudo credential, so until you add one, every template that
uses `become` (all but Ping) stops with `Missing sudo password`. Choose one of
these two ways.

**One sudo password for the practice targets.** Give `svc_ansible` the same
sudo password on every target in this seeded project. In **Key Store → New
Key**, create **Lab sudo** of type **Login with password**, leave **Username**
empty and enter that password. Then open **Inventory → Lab inventory file** and
select **Lab sudo** as **Sudo Credentials**. Leave the Username empty: Semaphore
passes it to Ansible as `--become-user`, so `svc_ansible` there would make every
privileged task run as `svc_ansible` instead of root. One inventory holds one
sudo credential, which is why this option needs the shared password.

**A different sudo password per target.** Keep the access chapter's unique
passwords and store each one as an encrypted host variable in the lab folder:

```bash
cd /opt/ansible-lab
mkdir -p inventories/host_vars
/opt/ansible-venv/bin/ansible-vault create inventories/host_vars/lab-ubuntu.yml
/opt/ansible-venv/bin/ansible-vault create inventories/host_vars/lab-alma.yml
sudo chgrp semaphore inventories/host_vars/*.yml
chmod 0640 inventories/host_vars/*.yml
```

Use the same Vault password for both files. Inside each editor, enter one line,
`ansible_become_password: "..."`, with that target's sudo password. Then
create a Key Store entry **Lab vault password** of type **Login with password**,
Username empty, containing the Vault password, and add it to every template
under **Ansible options → Vaults**, Ping included, because Ansible reads all
host variables. Encrypted files are still secrets: keep this folder's Git
history on the controller or in your own private repository.

**Check:** `find /opt/ansible-lab ! -group semaphore` prints nothing, then
**Baseline apply** changes both targets and an immediate repeat reports
`changed=0`.

**Concept:** the service reads the lab folder through the `semaphore` group,
which your account is deliberately not a member of, because that group can
also read the controller's secrets. New files and folders inherit the group
from the setgid folders, so create folders with plain `mkdir` rather than
`mkdir -m` or `install -d -m`, which can drop the setgid bit. Tools that write
private files, such as `ansible-vault create`, need the `chgrp` and `chmod`
shown above before Semaphore can read them.

## Do: the vendor STIG lessons

Two of the seeded templates wrap the operating-system vendor's own STIG
tooling, the same commands [chapter 9](09-security-benchmarks.md) walks through
by hand: the packaged SCAP Security Guide `stig` profile on RHEL and
AlmaLinux, and the Ubuntu Security Guide `disa_stig` profile on Ubuntu. The
guide adds no rules of its own.

- **STIG audit (vendor scan only)** installs the scanner where missing, runs
  the assessment, keeps the XML and HTML on the target under
  `/var/log/stig-practice/`, fetches them to the controller and prints outcome
  counts. It changes no policy. Ubuntu needs `usg` already installed through
  your own Ubuntu Pro attachment. Without it, that host fails with an
  explanation while the other hosts' scans still complete, so the task is
  marked failed but the AlmaLinux or RHEL results are in the same log.
- **STIG apply (vendor fixes, approval required)** scans, applies the vendor
  remediation with `oscap --remediate` or `usg fix`, optionally reboots, and
  scans again. It changes exactly one target per run: its Run dialog asks for
  that host in **Limit**, for example `lab-alma`, and for confirmation that a
  recovery point for it exists. A run selecting more than one host is refused
  before any connection. From the CLI the same gates are `--limit lab-alma`
  and `-e '{"stig_confirm": true}'`.

**Check:** after an audit, the task log ends with a JSON summary of pass,
fail, not-applicable and not-checked counts, and a path under the controller
home of the service or of your account, depending on where you ran it.

**Concept:** vendor remediation is not gentle. It commonly removes
passwordless sudo, tightens SSH and changes kernel parameters, and a first
pass often leaves failing rules that need a reboot or a manual decision. Run
it only against a disposable target with console access, and add a sudo
password credential to the inventory afterwards.

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
