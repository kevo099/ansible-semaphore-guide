# Azure: create, onboard and remove a lab

[Back to the guide](../README.md) · Used by [Stage 2](stage-2-existing-machines.md) and [Stage 3](stage-3-new-vms-cloud-init.md)

## Goal

Create Linux target VMs in Azure through Ansible, use cloud-init to prepare
the automation account with the same sudo and SSH rules as the rest of the
guide ([Stage 3](stage-3-new-vms-cloud-init.md)), and then run the lessons
against them. Also prepare a VM that already exists, over SSH or with Run
Command and no SSH at all, run the vendor STIG lessons on Azure targets, and
stop and remove the lab's compute deliberately. This page holds only what is
specific to Azure; the stages hold the steps that are the same everywhere.

| Edition and evidence | Scope |
| --- | --- |
| Tested with | `azure.azcollection` 4.0.0, ansible-core 2.21.4, `Standard_D2als_v6` and, in October in a new pay-as-you-go subscription, `Standard_D2als_v7`, in `eastus2`; targets Ubuntu 24.04 (plain and Ubuntu Pro images), AlmaLinux 9.8, Rocky Linux 9.8 (Marketplace image with a plan) and RHEL 9.8 (pay-as-you-go image); controllers Ubuntu 24.04 and AlmaLinux 9.8 in the same VNet |
| Files | [`platforms/azure/`](../platforms/azure/README.md), [`onboard/`](../onboard/README.md) and [`onboard/existing/bootstrap-existing-vm.yml`](../onboard/existing/bootstrap-existing-vm.yml); [the onboarding page](ONBOARDING.md) maps them |
| Evidence | [Azure validation record](validation/2026-09-azure.md), [onboarding and STIG record](validation/2026-09-onboard-stig.md) and [the October onboarding record](validation/2026-10-onboarding.md) |
| Known limits | One region and VM size; no Trusted Launch; targets reached inside one VNet, not across a VPN |

The playbooks create billable resources. Nothing in the starter lab calls
them; you run each one deliberately.

## Design your own cloud scope

Use a dedicated resource group and clear ownership tags for disposable tests.
Select a region and VM size that your subscription actually permits: check
the regional vCPU quota with `az vm list-usage --location REGION` and the size
list with `az vm list-skus`. Some subscriptions, such as free trials, allow only
a few vCPUs per region, which is less than a controller and three targets at
the guide's sizes need. A size can also be missing from one subscription: in
the October test a new pay-as-you-go subscription had no quota for
`Standard_D2als_v6` and 10 vCPUs per region for `Standard_D2als_v7`, which
held a controller and four targets. Both sizes attach disks over NVMe only, so
the image must support NVMe; the Marketplace images the examples name do.

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
be your workstation or the controller. The commands run in the repository
root: on the controller, the guide's folder; on a workstation, clone the guide
there first, with the `git clone` line of
[Stage 1](stage-1-controller.md#do-get-the-guide-onto-the-controller), and
work in that clone. The Azure SDK is large, so keep it in its own virtual
environment rather than the controller's `/opt/ansible-venv`:

```bash
python3.12 -m venv ~/azure-venv
~/azure-venv/bin/pip install ansible-core==2.21.4
~/azure-venv/bin/ansible-galaxy collection install -r platforms/azure/requirements.yml
~/azure-venv/bin/pip install \
  -r ~/.ansible/collections/ansible_collections/azure/azcollection/requirements.txt
```

ansible-core 2.21 needs Python 3.12 or later. On Ubuntu 24.04 that is `python3`,
with the `python3.12-venv` package; on Enterprise Linux 9 it is the separate
`python3.12` that [the Enterprise Linux installer](stage-1-controller.md)
installs, not the system `python3`.

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
cp platforms/azure/vars.example.yml platforms/azure/vars.yml
$EDITOR platforms/azure/vars.yml
```

Replace every `REPLACE_` value: subscription, owner and expiry tags, a private
address space you do not use elsewhere, a subnet inside it, one address per VM
inside the subnet, and the address prefix the targets accept SSH from. Keep
the quotes around the expiry date. The playbooks refuse to run while any
`REPLACE_` value remains or the owner or expiry tag is missing.

The playbooks also need two public keys, and stop before creating anything
when either file is missing or is not a public key:

- `azure_admin_public_key_file` is the key of each VM's administrator, which
  only your workstation holds. Make it an RSA key: after the vendor STIG,
  Enterprise Linux refuses Ed25519 keys, which OpenSSH now makes by default.

  ```bash
  ssh-keygen -t rsa -b 4096 -f ~/.ssh/azure_bootstrap
  ```

- `azure_automation_public_key_file` is the key Semaphore logs in with,
  copied into `platforms/azure/files/`, which Git ignores. On a controller
  made by either installer, that is the service key, whose copy the
  installer leaves as `~/svc_ansible.pub` on the controller, as
  [Stage 1](stage-1-controller.md#do-save-the-service-key) shows. Create the folder with
  `mkdir -p platforms/azure/files`, copy the key there as
  `platforms/azure/files/svc_ansible.pub` (from a workstation:
  `scp ADMIN@CONTROLLER_ADDRESS:svc_ansible.pub platforms/azure/files/`), and
  point the variable at it. Without a seeded controller, use
  `~/.ssh/ansible_lab.pub` from
  [the manual access page, step 1](manual-access.md#step-1-generate-the-automation-key).
  cloud-init takes one key; the password step can add more.

## Do: create the network

```bash
cd platforms/azure
~/azure-venv/bin/ansible-playbook -i localhost, network.yml
```

Run every Azure playbook from this `platforms/azure` directory on this machine.
This one creates the resource group with its tags, the targets' network
security group, the VNet and the subnet. The security group allows SSH from
`azure_target_ssh_source` and denies other traffic from inside the VNet.

## Optional Do: run the controller in Azure

`controller.yml` creates the controller from `azure_controller.image`, Ubuntu
24.04 in the example (the tests also used AlmaLinux 9.8), with a static public
address and a security group that allows SSH from `operator_cidr` and denies
all other inbound traffic. The explicit deny matters: Azure's default rules
would otherwise let every VM in the VNet reach every port on the controller.
The playbook owns every rule in that security group, so a rule you add by hand
disappears on its next run; to reach the UI over HTTPS, set
`azure_controller.https_cidr` to your own address prefix instead, and it opens
port 443 from there.

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
[Stage 1](stage-1-controller.md#do-install-with-the-installer) describes, from
the current release. A VM you create by hand in the portal can instead install
itself at its first boot, from one file pasted into **Advanced → Custom data**:
[install the controller at first boot](first-boot-controller.md#azure-custom-data).
`controller.yml` does not pass that file. To publish the UI over HTTPS in the same run, give the
installer the public address the certificate must name, as
[Stage 1's publishing section](stage-1-controller.md#optional-publish-the-ui-on-the-controllers-address)
explains:

```bash
sudo bash controller/install-controller.sh --apply --expose https --address CONTROLLER_PUBLIC_ADDRESS
```

Without `--address`, the certificate names the VM's private address, which
your browser does not use.

## Do: create the targets with cloud-init

```bash
~/azure-venv/bin/ansible-playbook -i localhost, targets.yml
```

Each target gets a network interface with a private static address and the
targets' security group, then a VM whose custom data is
[`onboard/new-vm/cloud-init.yaml`](../onboard/new-vm/cloud-init.yaml), with
the placeholder replaced by the automation public key. The same file works on
Ubuntu 24.04 and on AlmaLinux, Rocky Linux or RHEL 9, and you can paste it
into the portal yourself, as the next section shows. What it does at first
boot, what it prints and what it leaves out are in
[Stage 3](stage-3-new-vms-cloud-init.md); on Azure, the administrator, its key
and the hostname come from Azure's own provisioning, so the file needs nothing
else.

Each target's OS disk is 40 GB, except on Red Hat's images, which are 64 GB
themselves; Azure refuses an OS disk smaller than its image, so those get
64 GB. To choose another size, set `os_disk_size_gb` on the target in
`vars.yml`, as the commented RHEL 9 pay-as-you-go example in
`vars.example.yml` explains.

It sets no password: Azure advises against secrets in custom data. Until you
set one, as [Run Command](#set-the-sudo-password-without-ssh) or
[the bootstrap playbook](#do-finish-access-with-one-playbook) shows, or any
way in [Stage 3](stage-3-new-vms-cloud-init.md#do-set-the-sudo-password), the
account can log in but not use sudo. `targets.yml` renders the key as a
quoted string, so any key comment is safe. It also refuses `svc_ansible` as
`azure_admin_user`, because cloud-init gives the administrator passwordless
sudo.

**Check:** `sudo grep onboard /var/log/cloud-init-output.log` on a target
shows `onboard: svc_ansible is ready; set its sudo password next`, followed by
the lines for `add-target.sh`. Run it through Run Command if you have no SSH
path yet; Run Command's output comes through the authenticated control plane,
so its `fingerprint=` line is one Stage 4 can trust.

**Rocky Linux** comes from the Rocky Enterprise Software Foundation's
Marketplace image, which carries a plan: give the target the `plan` line that
`vars.example.yml` shows, and accept the image's terms once per subscription
before the first run:

```bash
az vm image terms show --urn resf:rockylinux-x86_64:9-base:latest --query accepted -o tsv
az vm image terms accept --urn resf:rockylinux-x86_64:9-base:latest
```

Without the plan, Azure refuses the VM with `VMMarketplaceInvalidInput`. The
foundation's Community Gallery images need no terms but declare no NVMe
support, so Azure refuses to create them on the NVMe-only sizes above.

An image is chosen when the VM is created; editing it in `vars.yml` later,
for example to the Ubuntu Pro image the STIG lessons need, changes nothing on
the existing VM. Recreate the VM instead. When a create fails, Azure can keep a
VM in the `Failed` state that later runs cannot update; delete it with
`az vm delete -g RESOURCE_GROUP -n VM_NAME --yes` and run `targets.yml` again.

### Paste it into the portal instead

For a VM you create by hand, make the filled copy on the controller as
[Stage 3](stage-3-new-vms-cloud-init.md#do-put-the-service-key-into-cloud-inityaml)
shows, or copy the file, replace `REPLACE_WITH_AUTOMATION_PUBLIC_KEY` with the
line of the controller's public key and keep the double quotes around it. If
the key's comment (the text after the base64 part) contains a `"` or a `\`,
leave the comment out. Paste the result into **Advanced → Custom data** when
you create the VM, or pass the file with `az vm create --custom-data`. The
test created an Ubuntu and an AlmaLinux VM this way; both reported
`svc_ansible is ready`. A third VM whose placeholder was left in reported
`status: error` with the missing-key message, and `svc_ansible` there had no
authorized key.

Azure's pay-as-you-go RHEL image already has working repositories through
Red Hat's cloud update service, so it needs no `subscription-manager`
registration: the test patched it with no extra step. The registration note in
[the manual access page, step 3](manual-access.md#step-3-prepare-a-dedicated-target-account)
applies to RHEL installed elsewhere.

The playbooks always pass their own network interface. Without one,
`azure_rm_virtualmachine` creates a public address and a security group itself.

cloud-init runs at first boot only. Updating a VM's custom data later does not
rerun it. For a VM that exists already, use
[Run Command](#do-onboard-an-existing-vm-with-run-command) or the
[bootstrap playbook](#when-the-vm-already-exists).

## Do: pin the targets' host keys

**Where: the controller, as your administrator account.** On a controller made
by either installer, `add-target.sh` does this for Semaphore with the values
each way of preparing a VM prints, as
[Stage 4](stage-4-add-target-first-job.md#do-add-the-target-with-add-targetsh)
shows. For your own terminal runs, and for the bootstrap playbook, which
checks host keys strictly, compare the key first. On Azure the trusted channel
is Run Command:

```bash
az vm run-command invoke -g RESOURCE_GROUP -n VM_NAME \
  --command-id RunShellScript \
  --scripts 'ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub'
ssh-keyscan -t rsa TARGET_PRIVATE_ADDRESS | ssh-keygen -lf -
```

When the two fingerprints match, connect once and accept that key, as
[Stage 2](stage-2-existing-machines.md#do-pin-the-vms-host-key-on-the-controller)
shows with a console in place of Run Command. Semaphore keeps its own copy, which `add-target.sh`
maintains.

## Do: finish access with one playbook

[`onboard/existing/bootstrap-existing-vm.yml`](../onboard/existing/bootstrap-existing-vm.yml)
prepares the account from the controller. On a VM that cloud-init prepared, it
sets the sudo password and checks what cloud-init wrote; on any other VM, it
does the whole job. What it does, its inventory and its command are in
[Stage 2](stage-2-existing-machines.md#do-let-the-controller-do-it-with-the-bootstrap-playbook).
Three things are specific to Azure:

- It connects as the VM's own administrator, which on Azure is the
  `admin_username` whose key only your workstation holds. Forward your
  workstation's agent for this step, as
  [the manual access page, step 3](manual-access.md#step-3-prepare-a-dedicated-target-account)
  describes, and close that session afterwards.
- The Azure administrator's sudo needs no password, so leave out `-K`.
- Pin each target's host key through Run Command first, as
  [above](#do-pin-the-targets-host-keys).

**Where: the controller, as your administrator account, in the guide's
folder,** not in `platforms/azure` and not on a workstation: the playbook's
paths are relative to the guide's folder, and `/opt/ansible-venv` and the
service key exist only on the controller.

```bash
cd ~/ansible-semaphore-guide
sudo cat /etc/semaphore/svc_ansible.pub > ~/svc_ansible.pub
/opt/ansible-venv/bin/ansible-playbook -i inventories/bootstrap.ini \
  onboard/existing/bootstrap-existing-vm.yml --limit lab-ubuntu -u YOUR_ADMIN \
  -e '{"automation_public_key_files": ["~/svc_ansible.pub"]}'
```

### When the VM already exists

This covers a VM created in the portal, with the Azure CLI, by another tool, or
before you used cloud-init. You do not need `network.yml` or `targets.yml`.
Choose one of two ways:

- **No SSH needed:** run
  [`onboard/existing/onboard-linux.sh`](../onboard/existing/onboard-linux.sh)
  through Azure Run Command, as the [next section](#do-onboard-an-existing-vm-with-run-command)
  shows. It needs only the Azure role that may run commands on the VM.
- **Over SSH:** make sure the controller can reach the VM's SSH port as its
  administrator, that the administrator's sudo works, and that the VM has
  Python 3. Pin its host key as above, add the VM to the bootstrap inventory
  with its address, and run `bootstrap-existing-vm.yml` for that host as its
  administrator.

Then continue with [Stage 4](stage-4-add-target-first-job.md).
In the first test the RHEL target, made with a plain `az vm create` and no
custom data, was prepared by the playbook alone, and a repeat run reported
`changed=0`. In the second, a plain Ubuntu and a RHEL VM were prepared by Run
Command alone.

## Do: onboard an existing VM with Run Command

**Where: the Azure portal, or any machine with the Azure CLI.** Run Command
runs a script as root through the VM agent, so it works before any SSH path
exists.
[`onboard/existing/onboard-linux.sh`](../onboard/existing/onboard-linux.sh)
does what the bootstrap playbook does and is safe to run again. It refuses
before any change when no given key can log in under the VM's SSH crypto
policy, for example an Ed25519 key on a host hardened to `FIPS:STIG`, or an
RSA key shorter than 2048 bits or than the server's `RequiredRSASize`. The
rest of what it checks and changes is in
[Stage 2](stage-2-existing-machines.md#what-the-script-and-the-playbook-check).

Edit the copy you run: replace `REPLACE_WITH_AUTOMATION_PUBLIC_KEY` with the
controller's public key, one key per line, between the two `END_OF_KEYS`
lines. Use the key Semaphore logs in with: on a seeded controller the service
key that `sudo cat /etc/semaphore/svc_ansible.pub` prints, otherwise
`~/.ssh/ansible_lab.pub` from
[the manual access page, step 1](manual-access.md#step-1-generate-the-automation-key).
Add your CLI key on a further line if you also run
[the command-line lessons](05-cli-lessons.md) from the terminal. The script
reads the keys through a quoted here-document, so a key comment with quotes or
`$(...)` is stored as text and never run. Set `CONTROLLER_ADDRESS` to the
controller's private address as the VM sees it, so the printed `address=` line
is the address the controller reaches and the SSH check evaluates the policy
for that address arriving on each of the VM's addresses and SSH ports. Empty,
it checks from loopback, which gives the same answer unless a `Match` rule, in
any file the configuration includes, depends on the client's address; the
script then stops and asks for `CONTROLLER_ADDRESS`.

In the portal: open the VM, then **Operations → Run command → RunShellScript**,
paste the edited script and select **Run**. Run Command starts scripts with
`/bin/sh`, which is dash on Ubuntu; the script starts bash itself. With the
Azure CLI:

```bash
az vm run-command invoke -g RESOURCE_GROUP -n VM_NAME \
  --command-id RunShellScript --scripts @onboard-linux.sh \
  --query 'value[0].message' -o tsv
```

Run Command returns only the last 4 KB of output, so the script sends package
output to `/var/log/ansible-lab-onboard.log` on the VM and prints the result
line last, `RESULT: OK` or `RESULT: FAILED: reason`. Compare the host-key
fingerprints it prints with `ssh-keyscan` from the controller, as
[pin the host keys](#do-pin-the-targets-host-keys) shows; this output comes
through the authenticated control plane. On a seeded controller, its
`fingerprint=` line is the one `add-target.sh` compares the scan with.

### Set the sudo password without SSH

The script never takes the password itself. Make a SHA-512 hash of it on the
controller, as
[Stage 2](stage-2-existing-machines.md#do-choose-a-sudo-password-and-make-its-hash)
shows; `openssl` prompts twice and shows nothing:

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
  includes the service key, saved as `~/svc_ansible.pub` on the machine that
  runs `az`. Run it from the guide's folder (the repository root), not from
  `platforms/azure`, because the `@` path is relative to it:

```bash
az vm run-command create -g RESOURCE_GROUP --vm-name VM_NAME --name onboard \
  --script @onboard/existing/onboard-linux.sh \
  --parameters ONBOARD_PUBLIC_KEYS="$(cat ~/svc_ansible.pub ~/.ssh/ansible_lab.pub)" \
    ONBOARD_CONTROLLER_ADDRESS=CONTROLLER_PRIVATE_ADDRESS \
  --protected-parameters ONBOARD_PASSWORD_HASH="$(openssl passwd -6)" \
  --timeout-in-seconds 900
az vm run-command show -g RESOURCE_GROUP --vm-name VM_NAME --name onboard \
  --instance-view --query instanceView.output -o tsv
az vm run-command delete -g RESOURCE_GROUP --vm-name VM_NAME --name onboard --yes
```

Leave out `~/.ssh/ansible_lab.pub` if you use no CLI key; leave out
`~/svc_ansible.pub` only on a controller you set up by hand.
Pass each parameter as `NAME=value`; in the test the form `name=X value=Y`
created parameters literally called `name` and `value`, and the script saw
none. Two keys in one parameter arrived intact. While `az` runs, other
accounts on your workstation can see the hash in its process list. Delete the
managed command afterwards; it otherwise stays on the VM's resource. A hash
from `openssl passwd -6` is accepted; a malformed one, such as `rounds=0`, is
refused before the account changes.

Without a hash the script keeps an existing password, and a new account has
none: its output then says `password: NOT SET`, and sudo waits until you set
one this way or with the bootstrap playbook. Save the plain password: Stage 4
gives it to Semaphore.

## Do: read a VM's values for the controller

**Where: the target VM's Azure Run Command → RunShellScript.** Every way of
preparing a VM above already ends with the values the controller needs. For a
VM that cloud-init prepared, or whose output you no longer have, paste the whole
[`onboard/inventory-info.sh`](../onboard/inventory-info.sh)
file into Run Command instead. It changes nothing: it only reads the VM's
hostname, OS, local IPv4 addresses, RSA host public key, account status and
sudo validation result. Its settings are explained in
[Stage 2](stage-2-existing-machines.md#do-read-a-prepared-vms-values-again).

Set `CONTROLLER_ADDRESS` at the top to the controller's private IP, so it
selects the target's source address for that route; this does not send a
network probe. Left empty, the VM must have exactly one global-scope IPv4
address, which on the examples' single-NIC targets it does.
`INVENTORY_NAME` defaults to the short hostname; a name the inventory
reserves, such as `localhost`, `lab` or `ubuntu`, is refused, and the script
asks you to set `INVENTORY_NAME`. Its output must stay below Run Command's
4 KB limit, and the script refuses rather than print a truncated line; in the
October test its output was under 500 bytes.

The output ends with data for the **controller**, not a command:

```text
Add this VM on the controller: in the guide's folder, run
  sudo bash controller/add-target.sh --from-info
then paste these lines and press Ctrl-D:
name=NAME
address=ADDRESS
group=GROUP
fingerprint=SHA256:...
```

Paste them into `add-target.sh --from-info` on the controller, as
[Stage 4](stage-4-add-target-first-job.md#do-add-the-target-with-add-targetsh)
shows: typed from that page, not copied from the VM's output, because a VM's
output is untrusted, as
[Stage 4](stage-4-add-target-first-job.md#why-the-vm-prints-lines-not-a-command)
explains. The fingerprint came through authenticated Run Command, so it is the
one `add-target.sh` may trust when it scans the VM. `add-target.sh` updates
the seeded **local file inventory**; a Static inventory saved in Semaphore or
an inventory fetched from Git is a separate source. The collector prints
warnings if the automation account, password, authorized keys or sudo
validation is incomplete; resolve them, then
[give Semaphore the sudo password](stage-4-add-target-first-job.md#do-give-semaphore-the-sudo-password),
with `sudo python3.12 controller/lab-sudo.py` on the controller,
and [run Ping and Baseline preview](stage-4-add-target-first-job.md#do-run-ping-and-baseline-preview).
The script prints no password, password hash or private key.

## Check: the same three layers, then the lessons

Run [the manual access page, step 5](manual-access.md#step-5-test-all-three-layers)
against each target, then the [lessons](05-cli-lessons.md), one target at a
time if their sudo passwords differ. What the test saw on all three targets:

- Ping succeeded; over direct SSH `sudo -n true` was refused, and `ansible -b`
  returned `0`.
- Baseline, Users and Webserver each reported changes on the first apply and
  `changed=0` on the immediate repeat; the Webserver second-page change applied.
- Patch without approval left each VM's required reboot to the operator; with
  `{"allow_reboot":true}` it rebooted the VM and reconnected.
- After those reboots, Ping and a Baseline repeat reported `changed=0`.
- Through Semaphore, with the host keys installed as
  [the manual access page, step 6](manual-access.md#step-6-install-target-trust-for-semaphore)
  shows, Ping and a Baseline preview succeeded against each target from a
  repository cloned over HTTPS.
- In the second test, seeded controllers ran the same way on Azure: the Ubuntu
  installer on the Azure controller and the Enterprise Linux installer on an
  AlmaLinux 9.8 VM in the same subnet each installed and seeded in about a
  minute, and after `add-target.sh`, Ping, Baseline preview, the STIG audit and
  a STIG apply with the approved reboot ran from the local lab folder with no
  clone step.

- In the October test, on a new pay-as-you-go subscription, every way of
  preparing a VM above gave the values `add-target.sh` needs, and
  `add-target.sh`, on an AlmaLinux 9.8 controller, added each target with
  them: RHEL 9.8 through pasted Run Command, AlmaLinux 9.8 through cloud-init
  and a managed Run Command, Rocky Linux 9.8 through cloud-init and the
  bootstrap playbook, and Ubuntu 24.04 Pro through the bootstrap playbook alone.
  Ping and Baseline preview then succeeded on all four. At the time, the
  scripts on the VMs printed a whole command rather than lines for
  `--from-info`. With the lines, on an Ubuntu 24.04 controller,
  `add-target.sh --from-info` added VMs from pasted Run Command output, from
  the end of a cloud-init log and from `inventory-info.sh`.

Repeat the provisioning playbooks, too: in the test, `network.yml`,
`controller.yml` and `targets.yml` reported `changed=0` on a second run, and the
resource group held the same resources before and after. `targets.yml` creates
its VMs together, so two took 43 seconds in October, and `power.yml`
deallocated two targets together in 54 seconds and started them in 84.

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
remediation an administrator with an RSA key can log in but not use sudo; on
Enterprise Linux, an administrator's Ed25519 key stops working entirely,
because the `FIPS:STIG` crypto policy refuses it. `svc_ansible`, with its RSA
key and its own password, keeps working. The Azure VM agent kept reporting
`Ready` and Run Command still ran as root on every hardened target, so Run
Command is the way back in: to set an administrator password, to change
`svc_ansible`'s, to rerun the onboarding script, or to unlock `svc_ansible`
with `faillock --user svc_ansible --reset` after three wrong sudo passwords
locked it; the STIG sets no automatic unlock.

**Passwords expire on Enterprise Linux.** On AlmaLinux, Rocky Linux and RHEL
the STIG sets a 60-day maximum password age on existing accounts,
`svc_ansible` included; `sudo chage -l svc_ansible` shows the date. Before it
passes, run `onboard-linux.sh` through Run Command with a new hash, pasted as
`PASSWORD_HASH` or passed as the protected `ONBOARD_PASSWORD_HASH`, which
also restarts the 60 days, and update the copy Semaphore or your inventory
uses. Once the password has expired, `svc_ansible` cannot log in without a
terminal at all: in the test, Ping itself failed with `Password change
required but no TTY available`, and the same Run Command with a new hash
brought the account back. The bootstrap playbook cannot do this on a hardened
target, because it logs in as the administrator, who no longer has sudo. The
Ubuntu STIG left the account's password age unchanged.

What the test saw, with the reboot approved:

| Target | Failing rules before → after | Passing before → after |
| --- | --- | --- |
| Ubuntu 24.04, Ubuntu Pro image, `disa_stig` | 67 → 8 | 54 → 209 |
| AlmaLinux 9.8, `stig` | 268 → 22 | 155 → 406 |
| RHEL 9.8 pay-as-you-go, `stig` | 262 → 15 | 170 → 420 |
| Rocky Linux 9.8, `stig` | 264 → 27 | 159 → 401 |

The October run reproduced the first three rows exactly and added Rocky
Linux.

After remediation, `svc_ansible` still logged in with its RSA key and used
sudo with its password, and Ping, Baseline and Webserver applied and then
repeated with `changed=0` on all three. The targets print the DoD login banner
and, on Enterprise Linux, use the `FIPS:STIG` crypto policy without FIPS mode.
A second remediation pass on RHEL, run from Semaphore, went from 16 failing
rules to 13, so a first pass leaves a short list for manual decisions rather
than converging with repetition.

## Do: stop compute, and remove the lab

**Where: back on the machine with your Azure login, in `platforms/azure`.**
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
