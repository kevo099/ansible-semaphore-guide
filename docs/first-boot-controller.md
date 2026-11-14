# Install the controller at first boot

[Back to the guide](../README.md) · [Stage 0: plan and create the VM](stage-0-plan.md) · [Stage 1: install the controller](stage-1-controller.md)

## Goal

You create the controller VM from a cloud image and hand it one file at
creation. At its first boot the VM fetches the guide and runs the installer by
itself. When it is done, PostgreSQL, Semaphore and Ansible are installed, the
project is seeded, and the readiness check has passed. This replaces the
typing of [Stage 1](stage-1-controller.md), not its result: the same installer
runs, with the same options.

The file is
[`controller/first-boot/user-data.yaml`](../controller/first-boot/user-data.yaml).
[The setup page](../site/README.md) fills it in from three questions and lists
the steps for your platform, with each command ready to copy.

Use this page for a VM you are about to create. On a VM that already runs,
cloud-init has had its first boot: follow Stage 1 there.

## Before you start

- A platform that can give a new VM a cloud-init file: Proxmox VE, Azure, or
  another hypervisor with a seed ISO.
- A **cloud image** of Ubuntu 24.04, or of AlmaLinux or Rocky Linux 9.4 or
  later; an installer ISO does not read the file.
- **RHEL:** a new RHEL VM is not registered and cannot install packages at
  its first boot. Create it, register it, and install with Stage 1. Azure's
  pay-as-you-go RHEL image is the exception: it has working repositories and
  installs at first boot.
- The controller's size from [Stage 0](stage-0-plan.md#the-machines): 2 vCPUs,
  4 GiB of memory and a 32 GiB disk.
- Outbound HTTPS from the VM to its package mirrors, PyPI and GitHub.
- The login of the administrator the VM will be created with.

## Do: fill in the four values

**Where: your workstation.** Open the setup page and answer its questions, or
copy the file and change the four lines under `content:`, nothing else:

```text
release=v1.13.0
admin=REPLACE_WITH_ADMIN_LOGIN
expose=tunnel
address=
```

| Value | Meaning |
| --- | --- |
| `release` | The guide's release tag to install. |
| `admin` | The login of the administrator the VM is created with. It will own the guide's folder, `~/ansible-semaphore-guide`, and the lab folder. |
| `expose` | `tunnel`: the UI stays on loopback, for an SSH tunnel. `https`: nginx also serves it on port 443 of the VM's address, as [`--expose https`](stage-1-controller.md#optional-publish-the-ui-on-the-controllers-address) does. |
| `address` | With `https` only: the IP address or DNS name you will browse to, which the certificate names. Empty means the VM's own address, which on a cloud VM behind NAT, as on Azure, is a private one. |

Save the result as `controller-first-boot.yaml`. It holds no secret, and the
installation prints none: the initial admin password is made on the VM and
stays in a root-only file there.

## Do: give the file to the new VM

The three ways are the ones of
[Stage 3](stage-3-new-vms-cloud-init.md), which hands a file to a new target
the same way and explains each command. Only the file and the VM's size
differ.

### Proxmox VE: vendor data

**Where: the Proxmox node's shell, as root.** Copy the file to the node's
snippets folder, create the VM from the cloud image, and attach the file as
vendor data before the first start:

```bash
qm create VMID --name controller --ostype l26 --cpu host --cores 2 --memory 4096 \
  --scsihw virtio-scsi-single --net0 virtio,bridge=vmbr0 \
  --serial0 socket --vga serial0 --agent enabled=1
qm set VMID --scsi0 STORAGE:0,import-from=/root/IMAGE_FILE
qm set VMID --ide2 STORAGE:cloudinit --boot order=scsi0
qm set VMID --ciuser ADMIN --sshkeys /root/ADMIN_KEY.pub --ipconfig0 ip=dhcp
qm resize VMID scsi0 32G
qm set VMID --cicustom "vendor=local:snippets/controller-first-boot.yaml"
qm start VMID
```

`ADMIN` is the login you put in the file. On AlmaLinux and Rocky Linux, add
`qm set VMID --rng0 source=/dev/urandom` before the start. Use `vendor=`, not
`user=`: Proxmox writes the user data itself, with your administrator and its
key, and `user=` would replace that.
[Stage 3](stage-3-new-vms-cloud-init.md#do-on-proxmox-attach-the-file-to-a-new-vm)
has the snippets storage, the image and the fixed-address form.

### Azure: custom data

**Where: the Azure portal.** Create the VM with **SSH public key**
authentication and the username you put in the file, allow inbound SSH only
from your own address, and paste the whole file into **Advanced → Custom
data**. `az vm create` takes the same file with `--custom-data`.
[Run the controller in Azure](platform-azure.md#optional-do-run-the-controller-in-azure)
describes the network around it.

### Another hypervisor: a seed ISO

**Where: any Linux machine that holds the file.** Build the seed ISO of
[Stage 3](stage-3-new-vms-cloud-init.md#do-on-another-hypervisor-build-a-nocloud-seed)
with this file as `vendor-data`, and attach it to the new VM before its first
boot. That seed creates no account of its own, so the administrator is the
image's default user: `ubuntu`, `almalinux` or `rocky`. Put that login in the
file.

## Check: read how the first boot ended

**Where: the new VM, over SSH as your administrator.** Compare the host-key
fingerprint SSH shows with the VM's console the first time. Then wait for
cloud-init and read the last lines of the log:

```bash
cloud-init status --wait
sudo tail -n 4 /var/log/ansible-guide-first-boot.log
```

```text
status: done
first-boot: the readiness check passed
first-boot: RESULT: OK
first-boot: next, open the SSH tunnel of docs/stage-1-controller.md, "Open Semaphore", and log in as admin.
first-boot: the initial password: sudo cat /etc/semaphore/initial-admin-password
```

The installation takes several minutes; allow ten. Continue with
[open Semaphore](stage-1-controller.md#do-open-semaphore) in Stage 1: the
tunnel, the initial password and the change of that password are the same.
With `expose=https`, the log also holds the installer's `Semaphore UI:` line
and the certificate's fingerprint:

```bash
sudo grep -E 'Semaphore UI|fingerprint' /var/log/ansible-guide-first-boot.log
```

## What the first boot does

1. cloud-init writes the four values to
   `/etc/ansible-semaphore-guide/first-boot.conf` and installs Git.
2. The file's one command fetches the guide at that release into
   `~/ansible-semaphore-guide`, as your administrator, and hands over to
   [`controller/first-boot.sh`](../controller/first-boot.sh).
3. That script runs the installer for your system with `--apply --editor
   ADMIN`, and `--expose https` when you chose it, then the readiness check.
4. Everything it printed is in `/var/log/ansible-guide-first-boot.log`, which
   root alone reads. The last lines say `RESULT: OK` or `RESULT: STOPPED:`
   with the reason.

It does not create the VM, register RHEL, open a firewall in front of the VM,
add machines or change the admin password. Those stay yours.

## When it stops

`cloud-init status` then says `error`, and the log's last line starts with
`first-boot: RESULT: STOPPED:`.

| The reason given | Cause | Next step |
| --- | --- | --- |
| `admin= in ... must be the login of this VM's administrator` | The placeholder was left in, or the value is empty | Create the VM again with the value filled in, or install by hand with [Stage 1](stage-1-controller.md) |
| `this VM has no account ... with a home folder` | The VM was created with another administrator than the file names | The same |
| `Git is not installed, so cloud-init could not install packages` | No working package repositories, as on RHEL before registration, or no outbound network | Fix that, then install by hand with Stage 1 |
| `could not fetch release ... from ...` | No outbound HTTPS to GitHub, or a release tag that does not exist; the log has Git's own message | Fix that, then install by hand with Stage 1 |
| `release ... has no controller/first-boot.sh` | The file names a release before `v1.13.0` | Use `v1.13.0` or later |
| `the installer ended with an error, shown above` | The installer's own stop, which the log shows | [Stage 1, when it fails](stage-1-controller.md#when-it-fails). The installer does not run twice on one VM, so after a failure half way a new VM is the short way |
| `the controller is installed, but its readiness check fails` | A check of [controller readiness](stage-1-controller.md#check-controller-readiness) fails | `sudo python3.12 controller/check-controller.py` names the check |

No line at all in the log, or no log: the VM never received the file. Check
the snippet's path and storage, the `cidata` label of the seed, that the VM
was made from a cloud image, and that no user data of your own has a
`write_files:` or `runcmd:`, which would replace the file's.

After a stop that you fixed on the VM, the script runs again by hand, from the
guide's folder: `sudo bash controller/first-boot.sh`.

## Concept

The first boot adds no second way to install. It runs the commands of Stage 1
in their order, unattended, and stops where they would stop. That keeps one
installer to test and one result to check, and a controller made this way is
updated, hardened and recovered like any other.

The file carries no secret because the platform keeps readable copies of it:
Proxmox as a snippet, Azure in the VM's properties, and the VM itself under
`/var/lib/cloud`. Everything secret is created on the VM.

## Next

[Open Semaphore](stage-1-controller.md#do-open-semaphore), then add machines
with [Stage 2](stage-2-existing-machines.md) or
[Stage 3](stage-3-new-vms-cloud-init.md).
