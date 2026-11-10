# Proxmox VE: worked examples

[Back to the guide](../README.md) · Used by [Stage 0](stage-0-plan.md), [Stage 2](stage-2-existing-machines.md) and [Stage 3](stage-3-new-vms-cloud-init.md)

## Goal

Build the guide's VMs on Proxmox VE and reach them from the Proxmox node: the
controller for Stage 0, plain VMs to onboard in Stage 2, and new VMs that
cloud-init prepares in Stage 3. The rest of the guide is the same on any
hypervisor; this page holds only what is specific to Proxmox.

The commands are written for Proxmox VE 8 and 9 and run in the **node's
shell, as root**: over SSH to the node, or **Shell** on the node in the web
UI. Each step also names the web UI path where it has one. `VMID`, `NAME`,
`STORAGE` and `vmbr0` stand for your own VM ID, guest name, disk storage (for
example `local-lvm`) and bridge. These steps work on a standalone node or an
existing cluster; they do not create or reconfigure a cluster. This guide
ships no fixed VM IDs, storage names or deletion script.

## End to end on Proxmox

1. [Stage 0](stage-0-plan.md): plan the lab, then build the **controller**
   VM, from a cloud image (below) or an ISO.
2. [Stage 1](stage-1-controller.md): install the controller and save the
   service key as `~/svc_ansible.pub`.
3. For each **new** target: [Stage 3](stage-3-new-vms-cloud-init.md#do-on-proxmox-attach-the-file-to-a-new-vm),
   a cloud-image VM with the guide's cloud-init file as a snippet. For a
   target that **already exists**: [Stage 2](stage-2-existing-machines.md).
4. [Stage 4](stage-4-add-target-first-job.md): add each target on the
   controller and run Ping and Baseline preview.

## Before you start

- Check the node's current guests, free memory and storage before you
  allocate anything, and choose unused VM IDs and guest names of your own.

  <!-- VERIFY-LIVE: on Proxmox VE 8 and 9, pvesm status, qm list and pvesh get /cluster/nextid print storages, guests and the next free VM ID -->
  ```bash
  pvesm status
  qm list
  pvesh get /cluster/nextid
  ```

- Get official media and verify it against the publisher's checksum and
  signature, as [Stage 0](stage-0-plan.md) describes.
- Choose amd64/x86_64 images: the controller's Semaphore binary is pinned to
  that architecture.

## Do: build a VM from an ISO

**Where: the Proxmox web UI.** This is the manual build: slower than a cloud
image, but it works for any installer and shows every choice.

1. Upload the official ISO to a storage meant for ISO images.
2. Use **Create VM**. Pick the resources in your plan, select the ISO, and
   connect the NIC to your existing trusted lab network.
3. Use a disk controller and NIC the guest supports. VirtIO networking and
   VirtIO SCSI are common Linux choices. Use the platform's supported firmware
   defaults consistently; changing BIOS/UEFI later can affect bootability.
   Give Enterprise Linux guests a [VirtIO RNG device](#do-give-enterprise-linux-guests-a-virtio-rng)
   as well.
4. Install the operating system. Create your own administrator and enable
   the OpenSSH server. Record the guest's actual address after installation.
5. Install the guest agent, enable **QEMU Guest Agent** in the VM's
   **Options**, and confirm that the UI sees the correct guest address.
6. Detach the installer media, confirm the boot order, then boot from the
   disk.
7. Leave **Start at boot** disabled unless you have deliberately planned the
   host's boot-time resource allocation.

On Ubuntu, after logging into the new guest:

```bash
sudo apt-get update
sudo apt-get install -y openssh-server sudo python3 python3-apt qemu-guest-agent
sudo systemctl enable --now ssh
sudo systemctl start qemu-guest-agent
```

On AlmaLinux or Rocky Linux 9:

```bash
sudo dnf install -y openssh-server sudo python3 python3-dnf python3-libselinux qemu-guest-agent
sudo systemctl enable --now sshd
sudo systemctl start qemu-guest-agent
```

An ISO-installed VM usually lets its administrator log in over SSH with a
password only. The bootstrap playbook in Stage 2 logs in with a key, so put
your key on the administrator first, or use the onboarding script, as
[Stage 2](stage-2-existing-machines.md) explains.

## Do: build a VM from a cloud image

**Where: the Proxmox node's shell, as root.** A cloud image is a disk that is
already installed; cloud-init sets it up at the first boot from the VM's
**Cloud-Init** settings. This is the quickest way to make the controller
VM for Stage 0, a plain VM to onboard in Stage 2, or, with the guide's file
attached, a Stage 3 VM.

1. **Download and check the image** on the node, for example into `/root`,
   with the URL from the publisher's download page in place of `IMAGE_URL`,
   and verify it as [Stage 0](stage-0-plan.md) describes. Do not infer the
   disk format from the filename: a `.img` download can contain qcow2 bytes.

   ```bash
   wget -P /root IMAGE_URL
   qemu-img info /root/IMAGE_FILE
   ```

2. **Create the VM and import the disk.** The example sizes follow
   [Stage 0](stage-0-plan.md): 4 GiB of memory and a 32 GiB disk for the
   controller, 3 GiB and 40 GiB for a target. The commands show the
   controller's; for a target, use `--memory 3072` here and `40G` in step 6.
   `--cpu host` gives the guest the
   node's CPU features; in a cluster with different CPUs, choose a common
   model instead.

   <!-- VERIFY-LIVE: on Proxmox VE 8 and 9: qm create with these options, and qm set --scsi0 STORAGE:0,import-from=FILE imports a qcow2 or raw cloud image as scsi0 -->
   ```bash
   qm create VMID --name NAME --ostype l26 --cpu host --cores 2 --memory 4096 \
     --scsihw virtio-scsi-single --net0 virtio,bridge=vmbr0 --agent enabled=1
   qm set VMID --scsi0 STORAGE:0,import-from=/root/IMAGE_FILE
   qm set VMID --boot order=scsi0
   ```

3. **Add the cloud-init drive and a serial console.** Ubuntu's cloud images
   expect a serial console; without one, the VM's console stays blank in
   places. The serial console is also how you read the VM from the node,
   [below](#do-read-a-vms-console-and-host-key-fingerprint-from-the-node).

   <!-- VERIFY-LIVE: on Proxmox VE 8 and 9, --ide2 STORAGE:cloudinit adds the cloud-init drive, and --serial0 socket --vga serial0 gives a working login on qm terminal for Ubuntu 24.04 and AlmaLinux 9 cloud images -->
   ```bash
   qm set VMID --ide2 STORAGE:cloudinit
   qm set VMID --serial0 socket --vga serial0
   ```

4. **Set the administrator, its key and the network** (the VM's
   **Cloud-Init** tab in the web UI). `--sshkeys` takes a file on the node
   that holds your public key; copy it there from your workstation first, for
   example with
   `scp ~/.ssh/id_ed25519.pub root@PROXMOX_NODE:/root/ADMIN_KEY.pub`.

   ```bash
   qm set VMID --ciuser ADMIN --sshkeys /root/ADMIN_KEY.pub --ipconfig0 ip=dhcp
   qm cloudinit dump VMID user
   ```

   The dump shows `hostname: NAME` and `fqdn: NAME`: Proxmox names the guest
   after the VM's `--name` and also sends that name as its full name, so
   Ubuntu and Enterprise Linux guests alike take it as their hostname.
   `--searchdomain lab.example` is optional; with it, the full name becomes
   `NAME.lab.example`. Set it, like every cloud-init setting, before the first
   boot: changing one later gives the VM new SSH host keys, as
   [Stage 3](stage-3-new-vms-cloud-init.md#do-on-proxmox-attach-the-file-to-a-new-vm)
   explains.

   For a fixed address, use `--ipconfig0 ip=VM_ADDRESS/PREFIX,gw=GATEWAY_ADDRESS` and
   `--nameserver DNS_SERVER_ADDRESS`. The administrator has no password unless you
   also set `--cipassword`; without one you log in with the key over SSH, and
   cannot log in on the console. Never name the administrator `svc_ansible`.

5. **Enterprise Linux only:** add the [VirtIO RNG](#do-give-enterprise-linux-guests-a-virtio-rng).

6. **Grow the disk, then start.** Cloud images ship small disks; resize
   before the first boot and cloud-init grows the partition to fill it.

   <!-- VERIFY-LIVE: qm resize VMID scsi0 32G sets the absolute size on Proxmox VE 8 and 9, and the guest's root filesystem fills it after first boot -->
   ```bash
   qm resize VMID scsi0 32G
   qm start VMID
   ```

7. **Wait for cloud-init**, in the guest, before any other work:

   ```bash
   cloud-init status --wait
   ```

8. **Guest agent.** The VM option is on (`--agent enabled=1`), but Ubuntu's
   cloud image does not include the agent. To let the web UI show the guest's
   address, install it inside the guest, then check from the node:

   <!-- VERIFY-LIVE: the Ubuntu 24.04 cloud image lacks qemu-guest-agent; after installing it, qm guest cmd VMID network-get-interfaces returns the guest's addresses -->
   ```bash
   sudo apt-get install -y qemu-guest-agent
   sudo systemctl start qemu-guest-agent
   ```

   ```bash
   qm guest cmd VMID network-get-interfaces
   ```

   The guide's cloud-init file does not install it; the agent is a Proxmox
   convenience, not something the guide depends on.

For a Stage 3 VM, run the `qm resize` of step 6, with the target's 40 GiB,
but not `qm start`: attach the cloud-init file first, as
[Stage 3](stage-3-new-vms-cloud-init.md#do-on-proxmox-attach-the-file-to-a-new-vm)
shows, then start it.

To make many VMs from one image, convert a VM that has never booted into a
template (`qm template VMID`) and clone it; each clone gets its own
cloud-init data. Do not clone a running controller, with its database and
credentials, as a generic template, and generalize any other OS template
with its documented procedure so new guests receive unique identities and
host keys.

## Do: enable snippets on a storage

**Where: the Proxmox node's shell, as root.** Proxmox reads custom cloud-init
files, called snippets, from a storage that allows the `snippets` content
type. The default `local` directory storage keeps them in
`/var/lib/vz/snippets/`. The content list is replaced as a whole, so read it
first and add `snippets` to what is there:

<!-- VERIFY-LIVE: on Proxmox VE 8 and 9, the dir: local entry in /etc/pve/storage.cfg lists its content; pvesm set local --content with the existing types plus snippets keeps them and creates /var/lib/vz/snippets -->
```bash
grep -A 4 '^dir: local$' /etc/pve/storage.cfg
pvesm set local --content iso,vztmpl,backup,snippets
ls -ld /var/lib/vz/snippets
```

Replace `iso,vztmpl,backup` with exactly the types the first command listed
after `content`. In the web UI: **Datacenter → Storage → local → Edit →
Content**, and add **Snippets**.

`local` is not shared: a snippet there exists on that node only, so a VM that
starts on another cluster node needs a copy on that node too. A shared
directory or NFS storage with `snippets` content avoids that. A snippet is
referenced as `STORAGE_ID:snippets/FILE`, for example
`local:snippets/onboard-new-vm.yaml`. Attaching it to a VM is part of
[Stage 3](stage-3-new-vms-cloud-init.md#do-on-proxmox-attach-the-file-to-a-new-vm).

## Do: give Enterprise Linux guests a VirtIO RNG

**Where: the Proxmox node's shell, not the guest.** If `systemctl --failed`
lists `rngd.service` and `journalctl -u rngd` shows that it found no entropy
source, the VM has no hardware random number device. The Rocky Linux image
enables `rngd` by default, and vendor STIG remediation enabled it on RHEL in
the verification run, so give every Enterprise Linux guest the device,
whether you installed from an ISO or a cloud image:

```bash
qm set VMID --rng0 source=/dev/urandom
```

In the web UI: **Hardware → Add → VirtIO RNG**. The device appears only after
the VM is stopped and started from the hypervisor, not after a reboot inside
the guest. Then run `systemctl --failed` again in the guest.

## Do: read a VM's console and host-key fingerprint from the node

**Where: the Proxmox node's shell, as root.** Several steps need a value read
through a channel that does not depend on the VM's own SSH host key, above all
the VM's RSA host-key fingerprint, which Stage 4 trusts. The hypervisor's
console is that channel. With the serial console from the cloud-image build:

<!-- VERIFY-LIVE: qm terminal VMID attaches to serial0 on Proxmox VE 8 and 9, shows a login prompt after Enter, and Ctrl-O detaches -->
```bash
qm terminal VMID
```

Press Enter for a login prompt, and press Ctrl-O to leave. Text there can be
copied from your terminal, unlike the graphical noVNC console. In the web UI,
the VM's **Console** opens the same serial console (xterm.js) when the VM has
one. Log in as the administrator, which needs a console password, then read
the fingerprint:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub
```

Without an administrator password, read what the VM prints at boot instead:
start it with `qm start VMID` and attach with `qm terminal VMID` straight
away. The guide's cloud-init file prints its `onboard:` lines, including
`fingerprint=`, at the end of the first boot, as
[Stage 3](stage-3-new-vms-cloud-init.md#check-read-what-cloud-init-printed)
shows.

### The guest agent is not a way in

`qm guest exec` runs a command in the guest through the QEMU guest agent, and
can look like a way to onboard a VM without SSH. Do not rely on it for this
guide:

<!-- VERIFY-LIVE: Ubuntu 24.04 cloud images ship without qemu-guest-agent; AlmaLinux/Rocky/RHEL 9 images ship it with guest-exec blocked by the RPC filter in /etc/sysconfig/qemu-ga; qm guest exec returns after its default timeout while a longer command keeps running -->
- Ubuntu's cloud image does not include the agent, so there is nothing to talk
  to until you install it.
- Enterprise Linux images include it but commonly block `guest-exec` in the
  agent's default policy. You do not need to relax that policy to complete
  this guide.
- `qm guest exec` returns after a timeout while a longer command keeps running,
  so a script such as `onboard-linux.sh` may still be working when it returns.

Use the console, or SSH as the administrator, as Stages 2 and 3 describe. The
agent remains useful for what it is meant for: showing the guest's address and
clean shutdowns.

## Check: inside every new guest

```bash
hostnamectl
ip -brief address
ip route
timedatectl status
systemctl --failed
python3 --version
```

Confirm that each guest has the intended unique hostname (not `localhost` or
the image's default), its own address, working package repositories and a
usable administrator login. On cloud images, also run
`cloud-init status --wait` and investigate errors rather than assuming that
SSH being up means the first boot has finished. Reboot each new VM once and
confirm that disk boot and networking return.

Before later hardening, take an appropriately documented clean checkpoint with
the VM stopped, and create an independent backup if you need recovery after
host or storage loss; see [chapter 10](10-recovery.md).

## Other hypervisors

Hyper-V, VMware and other platforms can provide the same guests. Use their
native creation tools and adapt virtual devices and guest agents; the rest of
the guide is the same. For a cloud image there, give cloud-init a NoCloud
seed ISO, as
[Stage 3](stage-3-new-vms-cloud-init.md#do-on-another-hypervisor-build-a-nocloud-seed)
shows. On Azure, see [the Azure page](platform-azure.md).

## Concept

A successful VM import is only the beginning. The machine becomes a usable
automation target after boot, networking, identity and access are all
verified. See [Proxmox VM documentation](https://pve.proxmox.com/pve-docs/qm.1.html)
and [cloud-init support](https://pve.proxmox.com/wiki/Cloud-Init_Support) for
the current platform-specific options.
