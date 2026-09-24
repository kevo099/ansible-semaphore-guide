# 2. Create the controller and targets

[Previous: design](01-design.md) · [Next: controller installation](03-controller.md)

## Goal

Create three clean Linux systems and verify their basic operation before
introducing automation.

## Do: obtain installation media

Use official sources:

- [Ubuntu Server downloads](https://ubuntu.com/download/server)
- [Ubuntu cloud images](https://cloud-images.ubuntu.com/)
- [AlmaLinux downloads](https://almalinux.org/get-almalinux/)
- [Rocky Linux downloads](https://rockylinux.org/download)
- [Red Hat Enterprise Linux downloads](https://developers.redhat.com/products/rhel/download)

Select Ubuntu 24.04 LTS for the controller and Ubuntu target, plus AlmaLinux 9
or Rocky Linux 9 for the second target. Choose amd64/x86_64 to match the pinned controller
binary. Verify the image against the publisher's checksum and signature
instructions before import; a checksum copied from the same untrusted source
as the image does not authenticate the publisher.

## Do: a manual Proxmox build

**Where: your hypervisor's management UI.** These steps apply to a standalone
node or an existing cluster; they do not create or reconfigure a cluster.

1. Check current guest inventory, available memory and storage. Select unused
   VM IDs and guest names of your own.
2. Upload the official ISO to storage intended for ISO files.
3. Use **Create VM**. Pick the resources in your worksheet, select the ISO,
   and connect the NIC to your existing trusted lab network.
4. Use a disk controller and NIC supported by the guest. VirtIO networking and
   VirtIO SCSI are common Linux choices. Use the platform's supported firmware
   defaults consistently; changing BIOS/UEFI later can affect bootability.
5. Install the operating system. Create your own administrator and enable
   OpenSSH server. Record the guest's actual address after installation.
6. Install the guest agent if your platform supports it, enable the corresponding
   VM option, and confirm that the UI sees the correct guest address.
7. Detach the installer media, confirm the boot order, then boot from the disk.
8. Repeat for the other two guests. Leave automatic VM start disabled unless
   you have deliberately planned the host's boot-time resource allocation.

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

Give Enterprise Linux guests a random number generator device: in Proxmox,
**Hardware → Add → VirtIO RNG**, or `qm set VMID --rng0 source=/dev/urandom`
for a stopped VM. Rocky Linux enables `rngd` by default, and vendor STIG
remediation enabled it on RHEL and Rocky Linux in the verification run. Without
a hardware entropy source the service fails and the guest reports a failed unit.

Guest-agent availability depends on the virtual hardware and the distribution's
policy. Some images allow IP discovery but disable command execution. Use the
guest console for bootstrap and trusted host-key inspection when necessary;
you do not need to relax guest-agent policy to complete this guide.

## Do: cloud images or another hypervisor

A cloud image can shorten repeat builds once you understand the manual path:

1. Authenticate the image and confirm its actual disk format.
2. Import it into a newly allocated VM and attach your platform's cloud-init
   configuration drive.
3. Supply a unique administrator, an SSH public key, network configuration and
   a unique hostname using your own platform's supported interface.
4. Boot it and wait for cloud-init to finish before configuration work.
5. Verify the address and SSH host-key fingerprint through the trusted console
   or authenticated provider control plane.

Enterprise Linux cloud images can ignore a short `hostname:` value in
cloud-init user data and keep the static hostname `localhost`, because their
cloud-init prefers a fully qualified name. Supply `fqdn:` as well, or set the
name afterwards with `sudo hostnamectl set-hostname NAME`, and confirm it with
the checks below.

Do not infer a disk format from its filename. A `.img` download can contain
qcow2 bytes; inspect it with `qemu-img info` on the system performing the import.
Do not clone a running controller's database and credentials as a generic
template. Generalize an OS template using its documented procedure so new
guests receive unique identities and host keys.

Hyper-V, VMware and other platforms can provide the same three guests. Use
their native creation tools and adapt virtual devices and guest agents; the
remaining Linux/Ansible workflow is the same. This repository intentionally
does not include fixed VM IDs, storage names or a deletion script.

## Check: inside every new guest

```bash
hostnamectl
ip -brief address
ip route
timedatectl status
systemctl --failed
python3 --version
```

Confirm that each guest has the intended unique hostname, its own address,
working package repositories and a usable administrator login. Reboot each
new VM once and confirm disk boot and networking return. On cloud images,
also run:

```bash
cloud-init status --wait
```

Investigate errors rather than assuming SSH availability means bootstrap has
finished. Before later hardening, take an appropriately documented clean
checkpoint with the VM stopped and create an independent backup if you need
recovery after host/storage loss.

## Concept

A successful VM import is only the beginning. The machine becomes a usable
automation target after boot, networking, identity and access are all verified.
See [Proxmox VM documentation](https://pve.proxmox.com/pve-docs/qm.1.html) and
[cloud-init support](https://pve.proxmox.com/wiki/Cloud-Init_Support) for the
current platform-specific options.
