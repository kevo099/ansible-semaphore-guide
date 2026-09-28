# Optional: apply the bootstrap model to Azure

[Back to the guide](../README.md)

## Goal

Create Linux target VMs in Azure through Ansible, use cloud-init to prepare
the automation account with the same sudo and SSH rules as
[chapter 4](04-access.md), and then run the lessons against them. Also prepare
a VM that already exists, over SSH or with Run Command and no SSH at all, run
the vendor STIG lessons on Azure targets, and stop and remove the lab's
compute deliberately.

| Edition and evidence | Scope |
| --- | --- |
| Tested with | `azure.azcollection` 4.0.0, ansible-core 2.21.4, `Standard_D2als_v6` in `eastus2`; targets Ubuntu 24.04 (plain and Ubuntu Pro images), AlmaLinux 9.8 and RHEL 9.8 (pay-as-you-go image); controllers Ubuntu 24.04 and AlmaLinux 9.8 in the same VNet |
| Files | [`examples/azure/`](../examples/azure/), [`examples/onboard/`](../examples/onboard/) and [`examples/bootstrap-existing-vm.yml`](../examples/bootstrap-existing-vm.yml) |
| Evidence | [Azure validation record](validation/2026-09-azure.md) and [onboarding and STIG record](validation/2026-09-onboard-stig.md) |
| Known limits | One region and VM size; no Trusted Launch; targets reached inside one VNet, not across a VPN |

The playbooks create billable resources. Nothing in the starter lab calls
them; you run each one deliberately.

## Design your own cloud scope

Use a dedicated resource group and clear ownership tags for disposable tests.
Select a region and VM size that your subscription actually permits: check
the regional vCPU quota with `az vm list-usage --location REGION` and the size
list with `az vm list-skus`. Some subscriptions, such as free trials, allow only
a few vCPUs per region, which is less than a controller and three targets at
the guide's sizes need.

Decide how the controller will reach the targets. The examples give the
targets private addresses only and allow SSH to them from one address prefix,
the controller's. That works when the controller is in the same VNet, as in
the tested lab, or reaches it through an approved private connection such as a
site-to-site VPN. A private address alone does not create a route. Avoid adding
a public address or opening SSH broadly to bypass an unresolved network path.
The optional Azure controller is the only VM with a public address, and its SSH
is open to your own address prefix alone.

Keep subscription identifiers, actual addresses and authentication material in
your private `vars.yml`, which Git ignores. Never bake a cloud credential into a
VM's cloud-init data or give a target the cloud administrator's private key.

## Do: prepare the Azure tooling

**Where: the machine that holds your Azure login, as your own account.** That can
be your workstation or the controller. The Azure SDK is large, so keep it in its
own virtual environment rather than the controller's `/opt/ansible-venv`:

```bash
python3.12 -m venv ~/azure-venv
~/azure-venv/bin/pip install ansible-core==2.21.4
~/azure-venv/bin/ansible-galaxy collection install -r examples/azure/requirements.yml
~/azure-venv/bin/pip install \
  -r ~/.ansible/collections/ansible_collections/azure/azcollection/requirements.txt
```

ansible-core 2.21 needs Python 3.12 or later. On Ubuntu 24.04 that is `python3`,
with the `python3.12-venv` package; on Enterprise Linux 9 it is the separate
`python3.12` that [chapter 3b](03-controller-el9.md) installs, not the system
`python3`.

The collection's requirement set resolved to 169 installed packages in the
test and took about 1.7 GB on disk. It lists several pre-release packages and
pulls in a transitive exact pre-release pin (`msal`). `pip` installs them as
listed; on an Ubuntu 24.04 controller it took about two minutes. Some other
installers, such as `uv`, refuse pre-releases unless you allow them. The file
does not lock every dependency, so record `pip freeze` for your own lab.

The playbooks authenticate with the Azure CLI login. Sign in, then select the
subscription explicitly:

```bash
az login
az account set --subscription YOUR_SUBSCRIPTION
az account show --query "{name:name, user:user.name}" -o table
```

Use an identity that can create resources in the lab's resource group; the
test used a Contributor role. Each playbook pins `ansible_python_interpreter`
to the virtual environment's Python. Without that, Ansible can discover the
system Python on `localhost` and fail with `Failed to import the required
Python library (azure)`.

## Do: describe your lab

**Where: the same machine, in the repository root.**

```bash
cp examples/azure/vars.example.yml examples/azure/vars.yml
$EDITOR examples/azure/vars.yml
```

Replace every `REPLACE_` value: subscription, owner and expiry tags, a private
address space you do not use elsewhere, a subnet inside it, one address per VM
inside the subnet, and the address prefix the targets accept SSH from. The
playbooks refuse to run while any `REPLACE_` value remains or the owner or
expiry tag is missing. `azure_admin_public_key_file` is your bootstrap
administrator's public key. `azure_automation_public_key_file` is a copy of the
controller's `~/.ssh/ansible_lab.pub` from [chapter 4, step 1](04-access.md#step-1-generate-the-automation-key).

## Do: create the network

```bash
cd examples/azure
~/azure-venv/bin/ansible-playbook -i localhost, network.yml
```

Run every Azure playbook from this `examples/azure` directory on this machine.
This one creates the resource group with its tags, the targets' network
security group, the VNet and the subnet. The security group allows SSH from
`azure_target_ssh_source` and denies other traffic from inside the VNet.

## Optional Do: run the controller in Azure

`controller.yml` creates an Ubuntu 24.04 controller with a static public
address and a security group that allows SSH from `operator_cidr` and denies
all other inbound traffic. The explicit deny matters: Azure's default rules
would otherwise let every VM in the VNet reach every port on the controller.

```bash
~/azure-venv/bin/ansible-playbook -i localhost, controller.yml
```

Before the first SSH connection, read the host key fingerprints through the
authenticated control plane rather than trusting the first network answer:

```bash
az vm run-command invoke -g RESOURCE_GROUP -n lab-controller \
  --command-id RunShellScript \
  --scripts 'cloud-init status --wait; ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub'
ssh-keyscan -t rsa CONTROLLER_PUBLIC_ADDRESS | ssh-keygen -lf -
```

Continue only when the two fingerprints match. Then install the controller as
[chapter 3](03-controller.md) describes. The test ran
`sudo bash scripts/install-controller.sh --apply` from the guide at tag
`v1.3.0`, and every readiness check passed.

## Do: create the targets with cloud-init

```bash
~/azure-venv/bin/ansible-playbook -i localhost, targets.yml
```

Each target gets a network interface with a private static address and the
targets' security group, then a VM whose custom data is
[`examples/onboard/cloud-init.yaml`](../examples/onboard/cloud-init.yaml), with
the placeholder replaced by the automation public key. The same file works on
Ubuntu 24.04 and on AlmaLinux, Rocky Linux or RHEL 9, and you can paste it
into the portal yourself, as the next section shows. At first boot it:

- creates `svc_ansible` with the automation public key and no password;
- writes chapter 4's sudoers rule and SSH drop-in;
- installs the Python package bindings the lessons need: `python3-apt` on
  Ubuntu; `python3-dnf` and `python3-libselinux` on Enterprise Linux;
- checks the sudo configuration and the effective SSH policy for
  `svc_ansible`, including that an authorized key is of a type and RSA size
  the server accepts and that `AuthorizedKeysFile` reads the file it wrote;
  it removes a sudoers rule that does not parse, sets the SSH drop-in aside
  only if the drop-in is what breaks `sshd -t`, and starts SSH if neither its
  service nor, on Ubuntu, its socket is running;
- makes cloud-init report an error when anything failed, including a key that
  is missing because the placeholder was not replaced. It checks the SSH
  policy from loopback, because the controller's address is unknown at first
  boot, and reports an error if a `Match` rule depends on the client's address.

It sets no password: Azure advises against secrets in custom data. Until you
set one, as [finish access](#do-finish-access-with-one-playbook) or
[Run Command](#set-the-sudo-password-without-ssh) shows, the account can log
in but not use sudo. `targets.yml` renders the key as a quoted string, so any
key comment is safe. It also refuses `svc_ansible` as `azure_admin_user`,
because cloud-init gives the administrator passwordless sudo.

**Check:** `sudo grep onboard /var/log/cloud-init-output.log` on a target
shows `onboard: svc_ansible is ready; set its sudo password next`. Run it
through Run Command if you have no SSH path yet.

### Paste it into the portal instead

For a VM you create by hand, copy the file, replace
`REPLACE_WITH_AUTOMATION_PUBLIC_KEY` with the line of the controller's public
key and keep the double quotes around it. If the key's comment (the text after
the base64 part) contains a `"` or a `\`, leave the comment out. Paste the
result into **Advanced → Custom data** when you create the VM, or pass the file
with `az vm create --custom-data`. The test created an Ubuntu and an AlmaLinux
VM this way; both reported `svc_ansible is ready`. A third VM whose placeholder
was left in reported `status: error` with the missing-key message, and
`svc_ansible` there had no authorized key.

Azure's pay-as-you-go RHEL image already has working repositories through
Red Hat's cloud update service, so it needs no `subscription-manager`
registration: the test patched it with no extra step. Chapter 4's registration
note applies to RHEL installed elsewhere.

The playbooks always pass their own network interface. Without one,
`azure_rm_virtualmachine` creates a public address and a security group itself.

cloud-init runs at first boot only. Updating a VM's custom data later does not
rerun it. For a VM that exists already, use
[Run Command](#do-onboard-an-existing-vm-with-run-command) or the
[bootstrap playbook](#when-the-vm-already-exists).

## Do: pin the targets' host keys

**Where: the controller, as your administrator account.** Read each target's
fingerprint through the control plane, as above or from the output of the
[Run Command script](#do-onboard-an-existing-vm-with-run-command), then scan it
over the private network and compare before trusting it:

```bash
ssh-keyscan -t rsa TARGET_PRIVATE_ADDRESS | ssh-keygen -lf -
```

Append each matching key to `~/.ssh/known_hosts`. Semaphore keeps its own copy;
see [chapter 4, step 6](04-access.md#step-6-install-target-trust-for-semaphore).

## Do: finish access with one playbook

[`examples/bootstrap-existing-vm.yml`](../examples/bootstrap-existing-vm.yml)
is the automated form of chapter 4, steps 3 and 4. On a VM that cloud-init
prepared, it sets the sudo password and checks what cloud-init wrote; on any
other VM, it does the whole job.
It needs what any Ansible run needs: SSH from the controller as an
administrator whose sudo works, and Python 3 on the VM, which mainstream cloud
images have. It then:

- ensures the package bindings, `sudo` and the SSH server are installed;
- creates or completes `svc_ansible` and authorizes exactly the public keys in
  `automation_public_key_files`, restoring SELinux labels on Enterprise Linux;
- sets the sudo password you type at its prompt, stored only as a hash;
- writes `/etc/sudoers.d/90-ansible-lab`, checked with `visudo`;
- writes the SSH drop-in and checks the whole configuration and the effective
  policy for `svc_ansible` before any reload. If another setting overrides the
  policy, it restores the previous drop-in, or removes the one it created, and
  stops without reloading SSH, so it cannot lock the account out;
- runs `sudo -k -n` as `svc_ansible` and fails if that succeeds, which catches
  a `NOPASSWD` rule elsewhere that would override the password requirement.

By default it authorizes `~/.ssh/ansible_lab.pub`. On a controller made by
either installer ([Ubuntu](03-controller.md) or
[Enterprise Linux](03-controller-el9.md)), list the exported service key
instead, and your CLI key too if you use one, or the run replaces the key
Semaphore logs in with:

```bash
/opt/ansible-venv/bin/ansible-playbook -i inventories/bootstrap.ini \
  examples/bootstrap-existing-vm.yml --limit lab-alma -u YOUR_ADMIN \
  -e '{"automation_public_key_files": ["~/svc_ansible.pub", "~/.ssh/ansible_lab.pub"]}'
```

**Where: the controller, as your administrator account, in the repository root.**
Put the VMs in a private inventory, for example `inventories/bootstrap.ini`:

```ini
[ubuntu]
lab-ubuntu ansible_host=ubuntu.example.test

[enterprise_linux]
lab-alma ansible_host=alma.example.test
```

It connects as the VM's own administrator, which on Azure is the
`admin_username` whose key only your workstation holds. Forward your
workstation's agent for this step, as chapter 4 describes, and close that
session afterwards. Run it for one host at a time, because each target gets
its own sudo password:

```bash
/opt/ansible-venv/bin/ansible-playbook -i inventories/bootstrap.ini \
  examples/bootstrap-existing-vm.yml --limit lab-ubuntu -u YOUR_ADMIN
```

Add `-K` when the administrator's own sudo asks for a password; the Azure
administrator's does not. The playbook refuses a run without a single-host
`--limit`, an unsupported system, or a password shorter than 12 characters. A
repeat run with the same password reports no changes.

### When the VM already exists

This covers a VM created in the portal, with the Azure CLI, by another tool, or
before you used cloud-init. You do not need `network.yml` or `targets.yml`.
Choose one of two ways:

- **No SSH needed:** run
  [`examples/onboard/onboard-linux.sh`](../examples/onboard/onboard-linux.sh)
  through Azure Run Command, as the [next section](#do-onboard-an-existing-vm-with-run-command)
  shows. It needs only the Azure role that may run commands on the VM.
- **Over SSH:** make sure the controller can reach the VM's SSH port as its
  administrator, that the administrator's sudo works, and that the VM has
  Python 3. Pin its host key as above, add the VM to the bootstrap inventory
  with its address, and run `bootstrap-existing-vm.yml` for that host as its
  administrator.

Then continue with [chapter 4, step 5](04-access.md#step-5-test-all-three-layers).
In the first test the RHEL target, made with a plain `az vm create` and no
custom data, was prepared by the playbook alone, and a repeat run reported
`changed=0`. In the second, a plain Ubuntu and a RHEL VM were prepared by Run
Command alone.

## Do: onboard an existing VM with Run Command

**Where: the Azure portal, or any machine with the Azure CLI.** Run Command
runs a script as root through the VM agent, so it works before any SSH path
exists. [`examples/onboard/onboard-linux.sh`](../examples/onboard/onboard-linux.sh)
does what `bootstrap-existing-vm.yml` does, and is safe to run again:

- creates or completes `svc_ansible` and authorizes exactly the keys you give
  it, writing the key file as that account so a link it planted cannot
  redirect root; SELinux labels are restored on Enterprise Linux;
- installs the Python bindings, `sudo` and the SSH server where missing;
- refuses before any change when no given key can log in under the VM's SSH
  crypto policy, for example an Ed25519 key on a host hardened to `FIPS:STIG`,
  or an RSA key shorter than 2048 bits or than the server's `RequiredRSASize`;
- enforces the modes of the home directory, `.ssh` and the key file on every
  run, because SSH ignores keys in a writable location;
- writes and enforces the sudoers rule and the SSH drop-in, checks the whole
  sudo configuration and rejects any `NOPASSWD` or `!authenticate` rule for the
  account, or a `rootpw`, `targetpw` or `runaspw` default;
- checks `sshd -t` and the effective SSH policy before reloading, and restores
  the previous drop-in and leaves SSH alone when a check fails;
- prints each change, the authorized key fingerprints and the host-key
  fingerprints, with `RESULT: OK` or `RESULT: FAILED: reason` as the last line.

Edit the copy you run: replace `REPLACE_WITH_AUTOMATION_PUBLIC_KEY` with the
controller's public key, one key per line, between the two `END_OF_KEYS`
lines. Use `~/.ssh/ansible_lab.pub` from
[chapter 4, step 1](04-access.md#step-1-generate-the-automation-key), and on a
seeded controller also the service key from
`sudo cat /etc/semaphore/svc_ansible.pub`. The script reads the keys through a
quoted here-document, so a key comment with quotes or `$(...)` is stored as
text and never run. Optionally set `CONTROLLER_ADDRESS` to the controller's
address as the VM sees it, so the SSH check evaluates the policy for that
address arriving on each of the VM's addresses and SSH ports. Empty, it checks
from loopback, which gives the same answer unless a `Match` rule, in any file
the configuration includes, depends on the client's address; the script then
stops and asks for `CONTROLLER_ADDRESS`.

In the portal: open the VM, then **Operations → Run command → RunShellScript**,
paste the edited script and select **Run**. With the Azure CLI:

```bash
az vm run-command invoke -g RESOURCE_GROUP -n VM_NAME \
  --command-id RunShellScript --scripts @onboard-linux.sh \
  --query 'value[0].message' -o tsv
```

Run Command returns only the last 4 KB of output, so the script sends package
output to `/var/log/ansible-lab-onboard.log` on the VM and prints the result
line last. Compare the host-key fingerprints it prints with `ssh-keyscan` from
the controller, as [pin the host keys](#do-pin-the-targets-host-keys) shows;
this output comes through the authenticated control plane. On a seeded
controller, it is the fingerprint `add-target.sh --fingerprint` asks for.

### Set the sudo password without SSH

The script never takes the password itself. Make a SHA-512 hash of it on
the controller; `openssl` prompts twice and shows nothing:

```bash
openssl passwd -6
```

Then either:

- **Paste it:** put the hash between the quotes of `PASSWORD_HASH=''` in your
  copy and run it as above. Azure sends the script to the VM encrypted, and the
  VM agent keeps a root-only copy under `/var/lib/waagent/run-command/download/`.
  The script deletes its own copy when a hash was pasted into it; copies from
  earlier runs remain until you delete them.
- **Pass it as a protected parameter** of a managed Run Command. The script
  file stays unedited, and the parameters reach it as environment variables.
  Azure shows the public keys when the command is read back, but never the
  protected hash. `ONBOARD_PUBLIC_KEYS` replaces the whole key list, so pass
  every key the account needs, one per line; on a seeded controller that
  includes the service key you copied to `~/svc_ansible.pub`:

```bash
az vm run-command create -g RESOURCE_GROUP --vm-name VM_NAME --name onboard \
  --script @examples/onboard/onboard-linux.sh \
  --parameters ONBOARD_PUBLIC_KEYS="$(cat ~/.ssh/ansible_lab.pub ~/svc_ansible.pub)" \
    ONBOARD_CONTROLLER_ADDRESS=CONTROLLER_PRIVATE_ADDRESS \
  --protected-parameters ONBOARD_PASSWORD_HASH="$(openssl passwd -6)" \
  --timeout-in-seconds 900
az vm run-command show -g RESOURCE_GROUP --vm-name VM_NAME --name onboard \
  --instance-view --query instanceView.output -o tsv
az vm run-command delete -g RESOURCE_GROUP --vm-name VM_NAME --name onboard --yes
```

Leave out `~/svc_ansible.pub` when Semaphore does not use a key of its own.
Pass each parameter as `NAME=value`; in the test the form `name=X value=Y`
created parameters literally called `name` and `value`, and the script saw
none. Two keys in one parameter arrived intact. While `az` runs, other accounts on your workstation can see the hash in
its process list. Delete the managed command afterwards; it otherwise stays
on the VM's resource. A hash from `openssl passwd -6` is accepted; a malformed
one, such as `rounds=0`, is refused before the account changes.

Without a hash the script keeps an existing password, and a new account has
none: its output then says `password: NOT SET`, and sudo waits until you set
one this way or with the bootstrap playbook.

## Do: add a target interactively from the controller

**Where: an interactive terminal on the controller**, after preparing the target
with cloud-init or the onboarding script. Use
[`scripts/add-target-interactive.py`](../scripts/add-target-interactive.py) when
you know its IP and want the controller to discover its hostname and OS. This
avoids copying a generated multi-line command between two consoles. Do not run
this interactive helper in Azure Run Command, which cannot answer its prompts.

Download and run the standalone file; it needs no repository checkout or Python
packages beyond the standard library:

```bash
curl -fsSL -o ~/add-ansible-target.py https://raw.githubusercontent.com/kevo099/ansible-semaphore-guide/main/scripts/add-target-interactive.py && sudo python3 ~/add-ansible-target.py
```

For an already-onboarded VM on a network you trust, you can instead accept its
first RSA key automatically and complete the controller setup without another
visit to the target console:

```bash
sudo python3 ~/add-ansible-target.py --trust-on-first-use
```

In this mode, enter the IP, accept or change the detected name, and confirm the
entry. The helper displays the received fingerprint for reference but does not
ask you to copy one. It still tests SSH login before saving anything, and an
existing different RSA key is always refused. Existing trust using another
host-key type requires the default console-verification mode. First-use trust accepts the key
received from the network; it does not independently establish the target's
identity. The default mode above keeps the console fingerprint check.

1. Enter the target's reachable **IPv4 address**. It connects only to that IP on
   SSH port 22; it does not scan the subnet.
2. In default mode, if the controller does not already trust its RSA host key, the helper asks
   for the `SHA256:...` fingerprint. Read it on the **target** using its console
   or Azure Run Command and paste just the fingerprint:

   ```bash
   ssh-keygen -l -E sha256 -f /etc/ssh/ssh_host_rsa_key.pub
   ```

3. The helper verifies the key and logs in as `svc_ansible` using the controller's
   `/etc/semaphore/svc_ansible` private key. It reads the short hostname and
   `/etc/os-release`, selecting `[ubuntu]` for Ubuntu 24.04 or
   `[enterprise_linux]` for RHEL, AlmaLinux or Rocky Linux 9.
4. Accept the detected inventory name with Enter, or type another plain hostname.
   Check the proposed entry and type `y` to save it.

The target must already allow this controller's public key for `svc_ansible`,
with Python 3 installed and SSH reachable. The seeded, unencrypted service key
is the default; the helper cannot unlock a passphrase-protected key or repair
onboarding, networking or sudo. It prompts for no target password. Existing RSA
trust must match; a changed key stops the helper for manual review.

It updates `/opt/ansible-lab/inventories/lab.ini` and
`/etc/semaphore/known_hosts`. Each changed file gets a `.before-add-TIMESTAMP`
backup alongside it. Original file ownership and modes stay intact. A declined
save, failed SSH login, unsupported OS or conflicting name/address leaves both
files unchanged. An identical repeat verifies SSH without adding duplicates.
Locks prevent two copies of this helper from editing together, and it refuses
files changed by another editor while the prompts were open. Backups remain for
manual recovery after a power loss or forced termination; review later edits
before restoring their contents into the original files.

Run it again for another target:

```bash
sudo python3 ~/add-ansible-target.py
```

For a customized seeded controller, `--lab-dir`, `--known-hosts` and `--key`
select the corresponding local paths. This updates the seeded **local file
inventory**, not a Static inventory stored inside Semaphore or a Git inventory.
In Semaphore select the local inventory and **Practice target SSH** credential,
then run **Ping** with Limit set to the new inventory name. Sudo is a separate
check: select the appropriate sudo credential (Username empty) and run
**Baseline preview**. No sudo password, credential, policy or template is
changed by this helper.

The interactive flow, strict SSH options, both first-connection trust modes, failures, backups,
repeat runs and rollback are covered by offline tests. SSH scans and remote
responses are simulated; a live controller/target run has not been established.

## Do: generate the controller inventory command

**Where: the target VM's Azure Run Command → RunShellScript.** After preparing
the target, paste the whole
[`examples/onboard/inventory-info.sh`](../examples/onboard/inventory-info.sh)
file into Run Command. It only reads the VM's hostname, OS, local IPv4 addresses,
RSA host public key, account status and sudo validation result.

Set `CONTROLLER_ADDRESS` at the top to the controller's IP. The collector selects
the target's source address for that route; this does not send a network probe.
If you leave it empty, the VM must have exactly one global-scope IPv4 address.
For multiple addresses you can instead set `TARGET_ADDRESS` explicitly; it must
belong to this VM. `INVENTORY_NAME` defaults to the short hostname, and `LAB_DIR`
is the controller's seeded lab folder, `/opt/ansible-lab` by default.

The output ends with a complete block beginning with `sudo python3` and ending
with `ADD_ANSIBLE_TARGET`. Copy that entire block into the **controller's**
terminal. It needs no guide checkout. It:

- checks that the existing inventory has the target's OS group and includes
  that group under `[lab:children]`;
- connects to target SSH on port 22, compares its RSA fingerprint with the one
  read through authenticated Run Command, and refuses a mismatch;
- refuses conflicting inventory entries or an existing different RSA host key;
- backs up each file it changes with a `.before-add-TIMESTAMP` suffix, adds
  the inventory entry, and records the verified key in
  `/etc/semaphore/known_hosts`, preserving the original files' permissions.

Repeating an unchanged successful add does not add duplicates or new backups.
This updates the seeded **local file inventory**; a Static inventory saved in
Semaphore or an inventory fetched from Git is a separate source.

The collector prints warnings if the automation account, password, authorized
keys or sudo validation is incomplete. Generating an inventory command does not
prove onboarding or connectivity. Resolve those warnings, select the SSH and
sudo credentials in Semaphore, and run **Ping** and **Baseline preview** with
the template's Limit set to this host. The script prints no password, password
hash or private key.

The output is capped below Azure action Run Command's last 4 KB limit.
The collector and generated command have offline tests with temporary inventory
files and simulated SSH scans; a live Azure/controller run of this helper has
not been established.

## Check: the same three layers, then the lessons

Run [chapter 4, step 5](04-access.md#step-5-test-all-three-layers) against each
target, then the [lessons](05-cli-lessons.md), one target at a time because
their sudo passwords differ. What the test saw on all three targets:

- Ping succeeded; over direct SSH `sudo -n true` was refused, and `ansible -b`
  returned `0`.
- Baseline, Users and Webserver each reported changes on the first apply and
  `changed=0` on the immediate repeat; the Webserver second-page change applied.
- Patch without approval left each VM's required reboot to the operator; with
  `{"allow_reboot":true}` it rebooted the VM and reconnected.
- After those reboots, Ping and a Baseline repeat reported `changed=0`.
- Through Semaphore, with the host keys installed as chapter 4, step 6 shows,
  Ping and a Baseline preview succeeded against each target from a repository
  cloned over HTTPS.
- In the second test, seeded controllers ran the same way on Azure: the Ubuntu
  installer on the Azure controller and the Enterprise Linux installer on an
  AlmaLinux 9.8 VM in the same subnet each installed and seeded in about a
  minute, and after `add-target.sh`, Ping, Baseline preview, the STIG audit and
  a STIG apply with the approved reboot ran from the local lab folder with no
  clone step.

Repeat the provisioning playbooks, too: in the test, `network.yml`,
`controller.yml` and `targets.yml` reported `changed=0` on a second run, and the
resource group held the same resources before and after.

## Optional Do: the vendor STIG lessons on Azure targets

[Chapter 9](09-security-benchmarks.md#the-seeded-stig-templates) describes the
two STIG playbooks, and they run unchanged against Azure targets. Four things
are specific to Azure.

**Ubuntu needs the Ubuntu Pro image.** The Ubuntu Security Guide ships only
through Ubuntu Pro. Azure's Ubuntu Pro image attaches Pro by itself and adds
Pro's charge to the VM's hourly price. Use it for an Ubuntu STIG target:

```yaml
image: {publisher: Canonical, offer: ubuntu-24_04-lts, sku: ubuntu-pro, version: latest}
```

Then enable the tool once, through Run Command or SSH:
`sudo pro enable usg && sudo apt-get install -y usg`. On the plain `server`
image, the audit stops for that host with the explanation chapter 9 describes.

**Take the recovery point as a disk snapshot.** An incremental snapshot of
the OS disk costs little and is quick to take:

```bash
disk=$(az vm show -g RESOURCE_GROUP -n lab-alma \
  --query storageProfile.osDisk.managedDisk.id -o tsv)
az snapshot create -g RESOURCE_GROUP -n snap-lab-alma-pre-stig \
  --source "$disk" --incremental true
```

It is in the same resource group. `remove.yml` then removes the lab's own
resources, lists the snapshot as left over and keeps the group; delete the
snapshot when you no longer need it and run `remove.yml` again, as the test did.

**The Azure administrator loses sudo.** cloud-init gives the administrator
passwordless sudo in `/etc/sudoers.d/90-cloud-init-users`, and the
administrator has no password. The vendor STIG comments that rule out, so after
remediation the administrator can log in but not use sudo. `svc_ansible`, with
its own password, keeps working. The Azure VM agent kept reporting `Ready` and
Run Command still ran as root on every hardened target, so Run Command is the
way back in: to set an administrator password, to change `svc_ansible`'s, or to
rerun the onboarding script.

**Passwords expire on Enterprise Linux.** On AlmaLinux and RHEL the STIG sets a
60-day maximum password age on existing accounts, `svc_ansible` included. Change
its sudo password within that time, with the bootstrap playbook or a new hash
through Run Command, and update the copy Ansible or Semaphore uses; otherwise
every task that uses sudo fails after the password expires. The Ubuntu STIG
left the account's password age unchanged in the test.

What the test saw, with the reboot approved:

| Target | Failing rules before → after | Passing before → after |
| --- | --- | --- |
| Ubuntu 24.04, Ubuntu Pro image, `disa_stig` | 67 → 8 | 54 → 209 |
| AlmaLinux 9.8, `stig` | 268 → 22 | 155 → 406 |
| RHEL 9.8 pay-as-you-go, `stig` | 262 → 15 | 170 → 420 |

After remediation, `svc_ansible` still logged in with its RSA key and used
sudo with its password, and Ping, Baseline and Webserver applied and then
repeated with `changed=0` on all three. The targets print the DoD login banner
and, on Enterprise Linux, use the `FIPS:STIG` crypto policy without FIPS mode.
A second remediation pass on RHEL, run from Semaphore, went from 16 failing
rules to 13, so a first pass leaves a short list for manual decisions rather
than converging with repetition.

## Do: stop compute, and remove the lab

**Where: back on the machine with your Azure login, in `examples/azure`.**
Shutting Linux down from inside the guest can leave Azure compute allocated and
billed. `power.yml` deallocates through Azure and then checks the power state
Azure reports:

```bash
~/azure-venv/bin/ansible-playbook -i localhost, power.yml -e azure_power=deallocated
~/azure-venv/bin/ansible-playbook -i localhost, power.yml -e azure_power=running
```

Add `-e include_controller=true` to include the controller. In the test, a
target deallocated, started again with the same private address, and answered
Ping. Disks and the static public address continue to cost money while
deallocated.

`remove.yml` removes only what the lab created, inside its resource group:

```bash
~/azure-venv/bin/ansible-playbook -i localhost, remove.yml -e remove_confirm=RESOURCE_GROUP
```

- It requires the resource group name as confirmation, and refuses before
  changing anything without it or with a wrong name.
- It removes a VM only when the VM's `owner` and `purpose` tags match
  `azure_tags`, and deletes the VM alone; its OS disk goes with it because the
  playbooks create it with the `Delete` option.
- It then deletes the lab's network interfaces and the controller's public
  address by name, the security groups and the VNet, and deletes the resource
  group only if nothing else is left in it. It never follows a VM's
  attachments into another resource group.
- On a lab that is already gone it ends without changes, and after a partial
  run it continues where it stopped.

`remove.yml` knows only the VMs in `azure_targets` and, unless you pass
`-e include_controller=false`, the controller. A VM you created another way,
such as the existing VM above, can still use the targets' security group and
subnet. Azure then refuses to delete them
(`InUseNetworkSecurityGroupCannotBeDeleted`) and the playbook stops with the
network and the resource group in place. Remove that VM with the tool that
created it, then run `remove.yml` again. Never point it at a shared resource
group.

## Concept

cloud-init establishes first-boot access. Ansible manages later desired state.
Cloud lifecycle controls decide whether the machine and its billable resources
remain allocated. Validate each boundary separately.
