# Stage 0: plan the lab and create the controller VM

[Back to the guide](../README.md) · [Next: Stage 1, install the controller](stage-1-controller.md)

## Goal

Decide what the lab contains and how its parts reach each other, start a
private worksheet, and create one clean VM: the controller. When this stage is
done, you can log in to the controller over SSH as your own administrator, and
you have checked its name, address, time, packages and host key.

You create **only the controller** now. The machines Ansible manages, the
targets, come later, because the quickest way to prepare a new target needs a
key that the controller creates in Stage 1.

## Before you start

- A hypervisor or cloud account where you may create VMs, with a console for
  each VM that does not depend on SSH working inside it.
- A workstation with an SSH client and a browser.
- Outbound HTTPS from the controller to its distribution's package mirrors,
  PyPI and GitHub; the installer downloads from all three.

## Do: plan the lab

**Where: your worksheet; nothing runs yet.**

### The machines

The following is a planning example for a small lab, not a vendor minimum:

| Role | Example name | OS | vCPU | RAM | Disk | Created in |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Controller | `controller.example.test` | Ubuntu 24.04, or RHEL, AlmaLinux or Rocky Linux 9.4 or later | 2 | 4 GiB | 32 GiB | This stage |
| Ubuntu target | `ubuntu.example.test` | Ubuntu 24.04 | 2 | 3 GiB | 40 GiB | Stage 2 or 3 |
| EL target | `alma.example.test` | AlmaLinux 9 | 2 | 3 GiB | 40 GiB | Stage 2 or 3 |

Keep additional RAM and storage free for the hypervisor and its other guests.
Start with one Semaphore task at a time. Larger inventories, report retention,
package upgrades and security scanners can need more resources. Recheck actual
available memory and disk before allocating VMs.

Rocky Linux 9 can replace the AlmaLinux target directly. RHEL 9 can replace it
if you have appropriate repository access. AlmaLinux is useful for general
Enterprise Linux administration; it does not turn an AlmaLinux benchmark into
Red Hat's RHEL benchmark.

Choose the controller's operating system now. [Stage 1](stage-1-controller.md)
has one installer for Ubuntu 24.04 and one for RHEL, AlmaLinux or Rocky Linux
9.4 or later. The Enterprise Linux installer uses the `python3.12` package and
the `postgresql:16` module stream, which first appear in release 9.4. A RHEL
controller must be registered with its BaseOS and AppStream repositories
enabled. Each installer refuses the other's operating system, so changing your
mind later means building a new controller VM. Both run only on amd64
(x86_64), to match the pinned Semaphore binary.

The guide is tested on Ubuntu 24.04 and Enterprise Linux 9. Two changes matter
before you add newer releases. Ubuntu 26.04 replaces classic sudo with sudo-rs,
whose password prompt ansible-core 2.20 and 2.21 do not recognize, so password
`become` fails on those targets; 2.22 recognizes its English prompt. Until then,
setting `ansible_become_exe: sudo.ws` for those hosts is the upstream
workaround; it was not tested here. RHEL 10 and Rocky Linux 10 require an
x86-64-v3 CPU, so give their VMs a CPU type that exposes it, such as `host` in
Proxmox; AlmaLinux 10 also ships an x86-64-v2 build.

The `.example.test` names are documentation examples. Use your own DNS or put
the actual guest addresses in the inventory. DNS integration, Active Directory
and a particular subnet layout are not prerequisites.

### The network paths

| Source | Destination | Required purpose |
| --- | --- | --- |
| Your workstation | Controller SSH, TCP 22 | Administration and the browser tunnel |
| Controller | Target SSH, TCP 22 | Ansible jobs |
| Controller and targets | Their DNS, time and package services | Normal operating-system operation |
| Controller | Public Git and release/package services, usually HTTPS | Read reviewed code and install dependencies |
| Controller loopback | TCP 3000 | Semaphore application |
| Controller loopback | TCP 5432 | PostgreSQL |
| Target loopback | TCP 8080 | Optional nginx lesson |

Allow only the administrative sources your network needs. Keep guest consoles
available while learning SSH and sudo. Stage 1 forwards your workstation's
`127.0.0.1:8088` over SSH to the controller's `127.0.0.1:3000`, so you do not
need to publish the application or database directly on your LAN or the
Internet.

Use your platform's existing networking rather than copying a stranger's
bridges, VLANs or firewall policy. Cloud users can use a VPN or a bastion for
private connectivity; on Azure, [the Azure page](platform-azure.md) explains
the boundary.

### The accounts

| Identity | Purpose | Where its secret belongs |
| --- | --- | --- |
| Your normal administrator | Controller/target setup and console recovery | Your password manager and workstation SSH configuration |
| `semaphore` service account | Runs the web application and Ansible child processes | No interactive login; service-owned state on the controller |
| PostgreSQL `semaphore` role | Owns the application's database | Private controller configuration |
| `svc_ansible` on each target | Receives automation over SSH and performs authorized sudo tasks | Public key on targets; private key and sudo credentials held by the operator/Key Store |
| Semaphore `admin` | First UI administrator | Unique local password; change and store it privately |
| `lab_alice`, `lab_bob` | Ordinary users created by the users lesson | Locked passwords; no keys or sudo are granted by that lesson |

Use a dedicated automation key for the lab: the installer creates one, the
service key, in Stage 1. Do not upload your everyday administrator key to
Semaphore. A managed target needs the automation **public** key; it never
needs the automation private key.

The lesson account receives broad sudo rights on disposable targets so it can
learn system administration. That is an explicit lab design choice, not a
recommendation to grant unrestricted access across an organization. A separate
sudo password helps distinguish authentication from privilege escalation;
the key and password still grant substantial authority to anyone controlling
the runner. This guide gives every lab target the same sudo password, which
Semaphore stores once.

### The order: controller first, then targets

1. **This stage:** create the controller VM only.
2. **[Stage 1](stage-1-controller.md):** install the controller. It creates
   the service key, `/etc/semaphore/svc_ansible.pub`, that every target must
   trust.
3. For each target, choose one:
   - **[Stage 2](stage-2-existing-machines.md):** the machine already exists,
     or you install it by hand from an ISO. You prepare it after it is running.
   - **[Stage 3](stage-3-new-vms-cloud-init.md):** you create a new VM from a
     cloud image with `cloud-init.yaml`, which carries the service key, so the
     VM arrives ready. This is why the controller has to exist first.
4. **[Stage 4](stage-4-add-target-first-job.md):** add each target on the
   controller and run the first jobs.

### The private worksheet

Copy this table into a private file or your password manager now, and fill it
in as you go. Each later stage tells you when a value appears. Never commit
the worksheet to Git. Rows marked secret belong only in your password manager.

| Field | Filled in during | Needed in | Secret |
| --- | --- | --- | --- |
| Controller VM name and ID on the hypervisor | Stage 0 | Recovery, cleanup | No |
| Controller address | Stage 0 | Every later stage | No |
| Controller SSH host-key fingerprint, read on its console | Stage 0 | Your first SSH login | No |
| Your administrator account on the controller | Stage 0 | Every later stage | Its password is |
| Controller operating system, and so its installer | Stage 0 | Stage 1 | No |
| Clean snapshot or backup of the fresh controller | Stage 0 | Stage 1, if the installer fails | No |
| The guide's folder on the controller | Stage 1 | Stages 2 to 4, updates | No |
| The lab folder | Stage 1 | Stage 4, updates | No |
| Where the initial Semaphore admin password is | Stage 1 | First login | The file path is not; its content is |
| Your changed Semaphore admin password | Stage 1 | Every login, updates | Yes |
| Copy of the service key on the controller | Stage 1 | Stages 2 and 3 | No |
| Address you browse to, and the certificate fingerprint if you publish the UI | Stage 1 | Every login | No |
| The lab sudo password for `svc_ansible` | Stage 2 or 3 | Stage 4, console recovery | Yes |
| For each target: VM name and ID, owner, disk location, cleanup method | Stage 2 or 3 | Rebuild or retire | No |
| For each target: the `name=`, `address=`, `group=` and `fingerprint=` lines | Stage 2 or 3 | Stage 4 | No |

## Do: obtain installation media

**Where: your workstation, or the hypervisor's image storage.** Use official
sources:

- [Ubuntu Server downloads](https://ubuntu.com/download/server)
- [Ubuntu cloud images](https://cloud-images.ubuntu.com/)
- [AlmaLinux downloads](https://almalinux.org/get-almalinux/)
- [Rocky Linux downloads](https://rockylinux.org/download)
- [Red Hat Enterprise Linux downloads](https://developers.redhat.com/products/rhel/download)

For the controller, select Ubuntu 24.04 LTS, or RHEL, AlmaLinux or Rocky Linux
9.4 or later, in amd64/x86_64. Verify the image against the publisher's
checksum and signature instructions before import; a checksum copied from the
same untrusted source as the image does not authenticate the publisher.

## Do: create the controller VM

**Where: your hypervisor's management UI or your cloud portal.** These steps
create one guest; they do not create or reconfigure a cluster.

1. Check current guest inventory, available memory and storage. Select an
   unused VM ID and a guest name of your own, and write both in the worksheet.
2. Create the VM with the controller's resources from the table above, and
   connect its network card to your existing trusted lab network.
3. Use a disk controller and network card the guest supports. VirtIO
   networking and VirtIO SCSI are common Linux choices. Use the platform's
   supported firmware defaults consistently; changing BIOS/UEFI later can
   affect bootability. Give an Enterprise Linux guest a VirtIO RNG device as
   well; the checks below explain why.
4. Install the operating system from the ISO, or import a cloud image as
   described below. Create your own administrator account and enable the
   OpenSSH server. Record the guest's actual address in the worksheet.
5. Install the guest agent if your platform has one, and enable the matching VM
   option, so the platform shows the guest's address.
6. Detach the installer media, confirm the boot order, then boot from the disk.
7. Leave automatic VM start disabled unless you have deliberately planned the
   host's boot-time resource allocation.

If the OpenSSH server is not running after installation, start it from the
VM's console. On Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y openssh-server
sudo systemctl enable --now ssh
```

On RHEL, AlmaLinux or Rocky Linux:

```bash
sudo dnf install -y openssh-server
sudo systemctl enable --now sshd
```

Guest-agent availability depends on the virtual hardware and the distribution's
policy. Some images allow address discovery but disable command execution. Use
the guest console for bootstrap and trusted host-key inspection; you do not
need to relax guest-agent policy to complete this guide.

**On Proxmox:** [the Proxmox page](platform-proxmox.md) builds the VM step by
step from an ISO or a cloud image, including the RNG device and the guest agent.

**On Azure:** the guide's playbooks can create the controller for you; see
[run the controller in Azure](platform-azure.md#optional-do-run-the-controller-in-azure).

### From a cloud image

A cloud image can shorten repeat builds once you understand the ISO path:

1. Authenticate the image and confirm its actual disk format.
2. Import it into a newly allocated VM and attach your platform's cloud-init
   configuration drive. Give an Enterprise Linux guest a VirtIO RNG device.
3. Supply a unique administrator, an SSH public key, network configuration and
   a unique hostname using your platform's supported interface.
4. Boot it and wait for cloud-init to finish before configuration work.
5. Verify the address and SSH host-key fingerprint through the trusted console
   or authenticated provider control plane.

The controller needs nothing from the guide's `cloud-init.yaml`; that file is
for targets, in Stage 3.

Enterprise Linux cloud images can ignore a short `hostname:` value in
cloud-init user data and keep the static hostname `localhost`, because their
cloud-init prefers a fully qualified name. Supply `fqdn:` as well, or set the
name afterwards with `sudo hostnamectl set-hostname NAME`, and confirm it with
the checks below.

Do not infer a disk format from its filename. A `.img` download can contain
qcow2 bytes; inspect it with `qemu-img info` on the system performing the
import. Do not clone a running controller's database and credentials as a
generic template. Generalize an OS template using its documented procedure so
new guests receive unique identities and host keys.

Hyper-V, VMware and other platforms can provide the same guests. Use their
native creation tools and adapt virtual devices and guest agents; the remaining
Linux and Ansible workflow is the same. This repository intentionally does not
include fixed VM IDs, storage names or a deletion script.

## Check

**Where: the controller's console, as your administrator.**

```bash
hostnamectl
ip -brief address
ip route
timedatectl status
systemctl --failed
python3 --version
```

Confirm that the guest has the intended unique hostname, its own address,
synchronized time, working package repositories and a usable administrator
login, and that `systemctl --failed` lists nothing. On a cloud image, also run
the following and expect `status: done`:

```bash
cloud-init status --wait
```

On Enterprise Linux, if `systemctl --failed` lists `rngd.service` and
`journalctl -u rngd` shows that it found no entropy source, the VM has no
hardware random number device. The Rocky Linux image enables `rngd` by
default, and vendor STIG remediation enabled it on RHEL in the verification
run, so give every Enterprise Linux guest the device, whether you installed
from an ISO or a cloud image. In Proxmox, use **Hardware → Add → VirtIO RNG**
in the VM's settings, or run `qm set VMID --rng0 source=/dev/urandom` in the
Proxmox node's shell, not in the guest. The device appears only after the VM
is stopped and started from the hypervisor, not after a reboot inside the
guest. Then run `systemctl --failed` again.

Still on the console, print the controller's SSH host-key fingerprints and
write them in the worksheet:

```bash
for key in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$key"; done
```

**Where: your workstation.** Log in over SSH:

```bash
ssh ADMIN@CONTROLLER_ADDRESS
```

The first connection shows a fingerprint and its key type. Accept it only if it
matches the line of the same type you read on the console. Then reboot the VM
once and confirm that it boots from disk and that its network and SSH return.

Before you go on, confirm the plan as well:

- You can identify each guest in the hypervisor and open its console.
- The controller will not be a managed target: you never add its own address
  in Stage 4 or onboard it in Stage 2.
- The targets you plan are disposable and have no existing application to
  preserve; the lessons change their configuration.
- You have a way to recover each VM that does not depend on working SSH inside
  it: its console, and a snapshot or backup.
- The hypervisor has enough free memory and storage for the VMs in your plan.

Before Stage 1, take a snapshot or backup of the stopped, clean controller VM.
The installer runs only once on a fresh VM; if it fails part way, returning to
this point is usually the quickest fix. Create an independent backup as well if
you need recovery after host or storage loss.

## Save these values

| Value | Where it came from | Needed in |
| --- | --- | --- |
| Controller VM name and ID | Your hypervisor or portal | Recovery, cleanup |
| Controller address | `ip -brief address` on the console | Stage 1 and every later stage |
| Controller SSH host-key fingerprints | `ssh-keygen -lf` on the console | Your first SSH login from any workstation |
| Your administrator login, and its password in your password manager | The OS installation or cloud-init | Every later stage |
| Controller operating system | Your choice above | Stage 1, which installer to run |
| Name of the clean snapshot or backup | Your hypervisor | Stage 1, if the installer fails |

## When it fails

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| The image's checksum does not match the publisher's | A damaged or substituted download | Do not use it; download again from the official source |
| `ssh` from the workstation times out or is refused | The OpenSSH server is not running, or a firewall or network path blocks TCP 22 | Start the server from the console as shown above; check the network path table |
| The first SSH fingerprint differs from the console's | You reached another machine, or the key changed | Stop; find out why before you accept any key |
| `hostnamectl` shows `localhost` on an Enterprise Linux cloud image | cloud-init kept the image's name without `fqdn:` | `sudo hostnamectl set-hostname NAME`, or supply `fqdn:` when you build the VM |
| `rngd.service` failed on Enterprise Linux | No hardware random number device | Add a VirtIO RNG device, then stop and start the VM from the hypervisor |
| `cloud-init status --wait` reports `error` | The user data or network configuration did not apply | Read `/var/log/cloud-init.log` on the console, fix the input, and build the VM again |
| `cat /etc/os-release` shows Enterprise Linux 9.3 or older | The image predates 9.4 | `sudo dnf -y upgrade`, reboot, and check again; register RHEL first |

## Concept

Provisioning creates a machine. Bootstrap establishes the access Ansible needs.
Configuration management brings that machine to a desired state. Semaphore
organizes the execution of that configuration management. Keeping these stages
distinct makes failures easier to locate.

A successful VM import is only the beginning. A machine becomes usable after
boot, networking, identity and access are all verified. See the
[Proxmox VM documentation](https://pve.proxmox.com/pve-docs/qm.1.html) and
[cloud-init support](https://pve.proxmox.com/wiki/Cloud-Init_Support) for the
current platform-specific options.

## Next

[Stage 1: install the controller](stage-1-controller.md).
