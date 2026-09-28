# Optional: apply the bootstrap model to Azure

[Back to the guide](../README.md)

## Goal

Create Linux target VMs in Azure through Ansible, use cloud-init to install the
automation public key, finish access with the same sudo and SSH rules as
[chapter 4](04-access.md), and then run the lessons against them. Also prepare
a VM that already exists, and stop and remove the lab's compute deliberately.

| Edition and evidence | Scope |
| --- | --- |
| Tested with | `azure.azcollection` 4.0.0, ansible-core 2.21.4, `Standard_D2als_v6` in `eastus2`; targets Ubuntu 24.04, AlmaLinux 9.8 and RHEL 9.8 (pay-as-you-go image); controller Ubuntu 24.04 in the same VNet |
| Files | [`examples/azure/`](../examples/azure/) and [`examples/bootstrap-existing-vm.yml`](../examples/bootstrap-existing-vm.yml) |
| Evidence | [Azure validation record](validation/2026-09-azure.md) |
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
targets' security group, then a VM whose cloud-init data comes from
[`templates/cloud-init-ubuntu.yaml.j2`](../examples/azure/templates/cloud-init-ubuntu.yaml.j2)
or [`templates/cloud-init-el.yaml.j2`](../examples/azure/templates/cloud-init-el.yaml.j2).
Both create `svc_ansible` with the automation public key and no password, and
install the Python package bindings the lessons need: `python3-apt` on Ubuntu;
`python3-dnf` and `python3-libselinux` on AlmaLinux, Rocky Linux or RHEL 9.
`python3-apt` does not exist in Enterprise Linux 9 repositories, and one
unknown package name makes cloud-init report an error. The playbook refuses an
automation key file that is not a single-line public key.

Azure's pay-as-you-go RHEL image already has working repositories through
Red Hat's cloud update service, so it needs no `subscription-manager`
registration: the test patched it with no extra step. Chapter 4's registration
note applies to RHEL installed elsewhere.

The playbooks always pass their own network interface. Without one,
`azure_rm_virtualmachine` creates a public address and a security group itself.

cloud-init runs at first boot only. Updating a VM's custom data later does not
rerun it. For a VM that exists already, use the next section's playbook.

## Do: pin the targets' host keys

**Where: the controller, as your administrator account.** Read each target's
fingerprint through the control plane, as above, then scan it over the private
network and compare before trusting it:

```bash
ssh-keyscan -t rsa TARGET_PRIVATE_ADDRESS | ssh-keygen -lf -
```

Append each matching key to `~/.ssh/known_hosts`. Semaphore keeps its own copy;
see [chapter 4, step 6](04-access.md#step-6-install-target-trust-for-semaphore).

## Do: finish access with one playbook

[`examples/bootstrap-existing-vm.yml`](../examples/bootstrap-existing-vm.yml)
is the automated form of chapter 4, steps 3 and 4. On a VM that cloud-init
prepared, it completes the account; on any other VM, it does the whole job.
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

By default it authorizes `~/.ssh/ansible_lab.pub`. On the
[seeded Enterprise Linux controller](03-controller-el9.md), list the exported
service key instead, and your CLI key too if you use one, or the run replaces
the key Semaphore logs in with:

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
before you used cloud-init. You do not need `network.yml` or `targets.yml`:

1. Make sure the controller can reach the VM's SSH port as its administrator,
   that the administrator's sudo works, and that the VM has Python 3. Pin its
   host key as above.
2. Add the VM to the bootstrap inventory with its address.
3. Run `bootstrap-existing-vm.yml` for that host, as its administrator.
4. Continue with [chapter 4, step 5](04-access.md#step-5-test-all-three-layers).

The test created the RHEL target with a plain `az vm create` and no custom data,
so `svc_ansible` did not exist. This playbook alone prepared it, and a repeat
run reported `changed=0`.

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

Repeat the provisioning playbooks, too: in the test, `network.yml`,
`controller.yml` and `targets.yml` reported `changed=0` on a second run, and the
resource group held the same resources before and after.

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
