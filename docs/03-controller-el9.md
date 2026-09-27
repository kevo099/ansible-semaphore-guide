# 3b. Install a seeded controller on Enterprise Linux 9

[Previous: controller on Ubuntu](03-controller.md) · [Next: SSH and sudo](04-access.md)

**Where: a fresh RHEL, AlmaLinux or Rocky Linux 9.4 or later x86_64 VM, using
your administrator account.** The installer needs the `python3.12` package and
the `postgresql:16` module stream, which Enterprise Linux 9 provides from
release 9.4. Run `sudo dnf -y upgrade` and reboot an older image first. RHEL
must be registered with its BaseOS and AppStream repositories enabled.

This is the Enterprise Linux alternative to the Ubuntu installer. It goes one
step further: after installing, it seeds Semaphore with a practice project
whose playbooks live in a **local folder on the controller**, so you can run
the first lessons before choosing a Git host.

## Goal

Get from a fresh VM to a Semaphore project with eleven scoped task templates in
one reviewed run, and understand what the installer decided for you.

## What the installer creates

| Layer | Result |
| --- | --- |
| Runtime | Python 3.12, Git, `/opt/ansible-venv` with ansible-core 2.21.4 and every Python dependency pinned in [`requirements-controller.txt`](../requirements-controller.txt) |
| Database | PostgreSQL 16 from the AppStream module stream, loopback only, SCRAM login |
| Application | Semaphore Community 2.19.12, checksum-verified, `127.0.0.1:3000`, hardened `semaphore.service` |
| Secrets | In `/etc/semaphore` (0750, root and the `semaphore` group): `config.json` (0640, readable by the service), the initial admin password and the `svc_ansible` RSA 4096 private key (root-only), and its public key (0644); no value is printed |
| Lab folder | `/opt/ansible-lab` owned by you, readable by the service: `ansible.cfg`, the seven playbooks, the report summarizer, an empty `inventories/lab.ini`, a local Git history with a `.gitignore` that keeps `inventories/`, `host_vars/` and `group_vars/` untracked |
| Semaphore objects | Project **Ansible Practice**; keys **None** and **Practice target SSH**; repository **Local lab folder**; inventory **Lab inventory file**; variable groups **Practice defaults** and **Allow required reboot**; eleven templates: Ping; Baseline preview; Baseline apply; Users; Webserver; Patch preview; Patch, no reboot; Patch, allow required reboot; STIG audit (vendor scan only); STIG apply (vendor fixes, approval required); STIG apply, allow required reboot |

Every lesson template sets its **Ansible options → Limit** to `lab`, the
explicit limit the playbooks' preflight requires. The two STIG apply templates
have no default limit: their Run dialog asks for exactly one host. The two
preview templates add `--check --diff` as CLI arguments. Only the templates
whose names end in “allow required reboot” receive `allow_reboot: true`. The
patch template then reboots only when the operating system reports that it
needs one. **STIG apply, allow required reboot** always reboots once after
remediation, because STIG changes such as kernel boot arguments and the crypto
policy take full effect only after a restart.

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
path, such as one under `/srv`. The installer refuses paths under `/home`,
`/root`, `/run/user`, `/tmp` and `/var/tmp`, which the hardened service cannot
see, and under `/var/lib/semaphore`, the service's own home. The folder's
parents must also let other accounts through, as `/opt` and `/srv` do: after
creating the folder, the installer confirms that the `semaphore` account can
read its inventory and stops before seeding if it cannot. The installer
refuses a VM that already has Semaphore, PostgreSQL data, the virtual
environment or the lab folder. It is not an upgrade tool.

The rest of this chapter uses the default `/opt/ansible-lab`. If you chose
`--lab-dir DIR`, use `DIR` wherever that path appears, and pass the same
`--lab-dir DIR` to `add-target.sh`.

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

Pass `--expose https` to the installer, or run
`sudo bash scripts/expose-semaphore.sh --mode https` later, to publish the UI
behind nginx on port 443 with a self-signed certificate.
[Browser access](appendices/browser-access.md#https-on-the-vms-address)
describes the modes, the checks, the cloud-firewall caution and
[the return to loopback](appendices/browser-access.md#return-to-loopback).

## Do: add a target without leaving the terminal

The inventory Semaphore reads is a file: `/opt/ansible-lab/inventories/lab.ini`.
Editing it changes the next run's targets. The helper below adds a host and
its **verified** host key in one step. First read the RSA host key's
fingerprint from the target's trusted console:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub
```

Use the RSA key, as the access chapter does. Vendor STIG remediation switches
Enterprise Linux to a FIPS-based crypto policy under which the target stops
offering its Ed25519 host key; a controller that pinned only that key then
refuses to connect.

Then on the controller:

```bash
sudo bash scripts/add-target.sh --name lab-alma --address alma.example.test \
  --group enterprise_linux --fingerprint 'SHA256:REPLACE_WITH_CONSOLE_VALUE'
```

With a custom `--lab-dir DIR`, add the same `--lab-dir DIR` here; the helper
otherwise looks in `/opt/ansible-lab`.

The helper scans the address and keeps only the key whose fingerprint matches
what you typed. It inserts the host under the chosen group, then appends that
key to `/etc/semaphore/known_hosts`. A mismatch changes nothing and prints the
scanned fingerprints so you can investigate. A name the inventory already has
is refused, and so is a group without a section in the inventory; neither
changes anything.

Each target also needs the `svc_ansible` account, its sudo rule and its SSH
drop-in. Before the check below, do steps 2 to 4 of
[the access chapter](04-access.md) for each target, and in step 3 authorize
this controller's key instead of a key from your home directory.
`/etc/semaphore` is readable only by root and the `semaphore` group, which
your account is not in, so copy the public key out with `sudo` first. Step 3's
`install` command expects the file name `ansible_lab.pub`:

```bash
sudo cat /etc/semaphore/svc_ansible.pub > ~/svc_ansible.pub
scp ~/svc_ansible.pub YOUR_ADMIN@ubuntu.example.test:ansible_lab.pub
scp ~/svc_ansible.pub YOUR_ADMIN@alma.example.test:ansible_lab.pub
```

If a copy is refused with `Permission denied (publickey)`, step 3 of the access
chapter shows how to log in with your workstation's key or paste the line
through the console.

That `install` command makes it the account's only authorized key. To run
chapter 5 from the terminal as well, create your own key in step 1, copy it to
each target as step 3 shows, and append it there instead of replacing the
file:

```bash
sudo tee -a /home/svc_ansible/.ssh/authorized_keys \
  < ~/ansible_lab.pub >/dev/null
```

Skip step 6 of the access chapter: it replaces `/etc/semaphore/known_hosts`,
which `add-target.sh` maintains. Reinstalling the controller creates a new key
pair, so replace the old public key on each target with the new one.

A rebuilt or restored target at the same address presents new host keys, and
the helper refuses an address it already trusts. After confirming why the key
changed, remove the old entry and the inventory line, then add the host again:

```bash
sudo ssh-keygen -R alma.example.test -f /etc/semaphore/known_hosts
sudo chown root:semaphore /etc/semaphore/known_hosts
sudo chmod 0640 /etc/semaphore/known_hosts
sed -i '/^lab-alma /d' /opt/ansible-lab/inventories/lab.ini
```

`ssh-keygen -R` rewrites the file as `root:root`; without the `chown`, the
service can no longer read it and every job fails host verification.
`check-controller.py` reports this as `service_can_read_known_hosts`.

**Check:** run the **Ping** template. The task log shows no clone step, its
paths are under `/opt/ansible-lab`, and each host answers with its
distribution.

**Concept:** a file inventory tied to a local repository is read at run time.
There is nothing to sync and nothing cached; the file is the truth. The trade
is that a half-edited file is also the truth. The folder's `.gitignore` keeps
`inventories/` out of Git, so Git cannot show or undo an inventory edit: copy
`lab.ini` aside before editing it by hand, and rely on
[chapter 10](10-recovery.md)'s capture of the lab folder for recovery. The
[Git chapter](07-git-and-vscode.md) covers the playbooks.

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
host variables. Encrypted files are still secrets. The lab folder's
`.gitignore` keeps `inventories/`, and these files with it, out of Git; for a
folder installed before that file existed, see
[moving to a real repository](#do-move-to-a-real-repository-later).

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

The three seeded STIG templates are optional. The audit changes no security
policy; the two apply templates do. Do not run them while learning the
installation. They are
described in [chapter 9](09-security-benchmarks.md#the-seeded-stig-templates),
after the recovery preparation they depend on.

## Do: move to a real repository later

Semaphore reads the **Local lab folder** straight from its working tree,
uncommitted edits included. When you want tasks to run only reviewed, pushed
code, follow [moving the lab folder to Git](appendices/git-migration.md). It
covers the private files to untrack first, the history review before any push,
and why **Lab inventory file** stays bound to the local folder.

## Enterprise Linux differences worth knowing

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
  `scripts/expose-semaphore.sh --mode https`) adds the `https` service to an
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

See [validation and limitations](VALIDATION.md) for what this path has and
has not been exercised against.
