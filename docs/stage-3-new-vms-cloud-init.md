# Stage 3: pre-deploy new VMs with cloud-init

[Back to the guide](../README.md) · [Previous: Stage 1, the controller](stage-1-controller.md) (for a machine that already exists: [Stage 2](stage-2-existing-machines.md)) · [Next: Stage 4, add the target and run the first job](stage-4-add-target-first-job.md)

## Goal

You create a new VM from a cloud image and hand it
[`onboard/new-vm/cloud-init.yaml`](../onboard/new-vm/cloud-init.yaml) at
creation. At its first boot the VM prepares the automation account,
`svc_ansible`, by itself. When this stage is done, the VM has printed its
`name=`, `address=`, `group=` and `fingerprint=` lines, `svc_ansible` has a
sudo password, and you have saved both for Stage 4.

Use this stage for VMs you are about to create. For a machine that already
runs, cloud-init has had its first boot: use
[Stage 2](stage-2-existing-machines.md) instead. Both stages end in the same
place.

## Before you start

- **A controller from Stage 1**, and on it the service key saved as
  `~/svc_ansible.pub`, as
  [Stage 1](stage-1-controller.md#do-save-the-service-key) shows, and the
  guide's folder, `~/ansible-semaphore-guide`.
- **A cloud image of a supported system**: Ubuntu 24.04, or AlmaLinux, Rocky
  Linux or RHEL 9, the systems `cloud-init.yaml` names in its header. Use the
  official image and verify it as [Stage 0](stage-0-plan.md) describes.
  Cloud images ship cloud-init; an installer ISO does not run this file.
- **A platform that hands cloud-init its data at the first boot**: Proxmox VE
  (worked below), any hypervisor that can attach a small ISO (a NoCloud seed,
  below), or Azure (custom data).
- **An administrator for the VM** other than `svc_ansible`, with your own SSH
  public key. The VM's administrator is how you reach it if something goes
  wrong, and how you set the sudo password below. Never name it `svc_ansible`:
  cloud-init gives the administrator passwordless sudo, and the file's checks
  then fail on purpose.

What the file does at the first boot, as its own text shows:

- creates `svc_ansible` with the service key, a login shell and **no
  password**, and keeps the image's default user. Its `users:` list does that
  where cloud-init applies it. Where the platform's own user data replaces
  that list, as Proxmox's does, the file's script creates the account itself
  and says so: `onboard: created svc_ansible here, ...`;
- writes the sudoers rule `/etc/sudoers.d/90-ansible-lab`
  (`svc_ansible ALL=(ALL:ALL) ALL`, so sudo asks for its password) and the SSH
  drop-in `/etc/ssh/sshd_config.d/70-ansible-lab.conf` (public key only for
  `svc_ansible`);
- installs the Python bindings the lessons need where they are missing:
  `python3-apt` on Ubuntu; `python3-dnf` and `python3-libselinux` on
  Enterprise Linux;
- checks the sudo rule, the effective SSH policy for `svc_ansible`, its key
  type and size, `AuthorizedKeysFile`, and any `AllowUsers`, `AllowGroups`,
  `DenyUsers` or `DenyGroups` rule; it reloads or starts SSH;
- prints `onboard: svc_ansible is ready; set its sudo password next` and the
  lines for `add-target.sh --from-info`, or `onboard: ERROR: ...` lines and
  `onboard: FAILED; see the errors above`, which make cloud-init report an
  error.

What it does not do: it sets no sudo password, creates no administrator, sets
no hostname and configures no network; your platform does those. cloud-init
reads the file at the **first boot only**. It contains no secret: only the
service's public key.

## Do: put the service key into cloud-init.yaml

**Where: the controller, as your administrator account, in the guide's folder.**

The file has exactly one placeholder: the quoted string
`"REPLACE_WITH_AUTOMATION_PUBLIC_KEY"`. Nothing else is filled in by hand;
the VM finds its own name, address, group and fingerprint at boot. Make a
filled copy from `~/svc_ansible.pub` with
[`onboard/new-vm/fill-cloud-init.sh`](../onboard/new-vm/fill-cloud-init.sh)
rather than pasting the 740-character key by hand:

```bash
cd ~/ansible-semaphore-guide
bash onboard/new-vm/fill-cloud-init.sh ~/svc_ansible.pub > ~/onboard-new-vm.yaml
```

It prints `cloud-init.yaml` with only the quoted placeholder replaced by the
key, quotes kept. It refuses a key file that does not hold exactly one
single-line OpenSSH public key, and a key whose comment (the text after the
base64 part) contains a `"` or a `\`; remove such a comment from your copy of
the key and run it again. On an error it prints the reason and writes nothing
to standard output, so `~/onboard-new-vm.yaml` is then empty. The installer's
key has the comment `ansible-practice`, which is safe. You can also edit a
copy by hand, following the same rules: keep the double quotes, and leave out
a comment that holds a `"` or a `\`.

**Check** that the file is not empty, the placeholder is gone, and the result
still parses as YAML with the key where cloud-init reads it. The controller's
Ansible environment has the YAML library:

```bash
grep -c REPLACE_WITH ~/onboard-new-vm.yaml
/opt/ansible-venv/bin/python -c 'import sys, yaml; d = yaml.safe_load(open(sys.argv[1])); print(d["users"][1]["name"], d["users"][1]["ssh_authorized_keys"][0][:20])' ~/onboard-new-vm.yaml
```

```text
0
svc_ansible ssh-rsa AAAAB3NzaC1y
```

Where cloud-init is installed, for example on an Ubuntu 24.04 controller,
also validate it as cloud-config:

```bash
cloud-init schema --config-file ~/onboard-new-vm.yaml
```

It prints `Valid schema` and the file's path; warnings above that line about
files it may not read are harmless. The same filled copy serves every new VM
that this controller manages; keep it with the guide's folder, not in a
public repository of your own (it holds only a public key, but it is your
lab's).

## Do: on Proxmox, attach the file to a new VM

**Where: the Proxmox node's shell, as root, unless a step says otherwise.**
[Proxmox VE: worked examples](platform-proxmox.md) explains each command;
this section gives the order. `VMID`, `NAME`, `STORAGE` (a storage for VM
disks, such as `local-lvm`) and `vmbr0` are your own values. Check the node's
free memory and storage first.

On Proxmox the file is **vendor data**. Proxmox writes each VM's user data
itself, from the settings on the VM's **Cloud-Init** panel: the administrator,
its SSH key, the hostname and the network. Vendor data sits beside that, so
the panel keeps working, and one copy of the file serves every VM.

1. **Once per storage: allow snippets.** cloud-init files live on a storage
   with the `snippets` content type. On the default `local` directory storage
   that is `/var/lib/vz/snippets/`; the
   [snippets section](platform-proxmox.md#do-enable-snippets-on-a-storage)
   shows how to enable it without dropping the content types it already has.

2. **Copy the filled file to the node.** From the controller, for example:

   ```bash
   scp ~/onboard-new-vm.yaml root@PROXMOX_NODE:/var/lib/vz/snippets/onboard-new-vm.yaml
   ```

   A snippet on a storage that is not shared exists on that node only. A VM
   started on another node of a cluster needs the file there too.

3. **Create the VM from the cloud image**, as
   [the cloud-image example](platform-proxmox.md#do-build-a-vm-from-a-cloud-image)
   explains, but do not start it yet:

   ```bash
   qm create VMID --name NAME --ostype l26 --cpu host --cores 2 --memory 2048 \
     --scsihw virtio-scsi-single --net0 virtio,bridge=vmbr0 \
     --serial0 socket --vga serial0 --agent enabled=1
   qm set VMID --scsi0 STORAGE:0,import-from=/root/IMAGE_FILE
   qm set VMID --ide2 STORAGE:cloudinit --boot order=scsi0
   qm set VMID --ciuser ADMIN --sshkeys /root/ADMIN_KEY.pub --ipconfig0 ip=dhcp
   qm resize VMID scsi0 20G
   ```

   For a fixed address use `--ipconfig0 ip=VM_ADDRESS/PREFIX,gw=GATEWAY_ADDRESS` and
   `--nameserver`. Proxmox names the guest after the VM's `--name`, on Ubuntu
   and on Enterprise Linux alike, so choose a name the inventory can use: not
   `localhost`, `lab`, `ubuntu` or `enterprise_linux`.

4. **Enterprise Linux only: add the VirtIO RNG.** Without it, Rocky Linux's
   `rngd` fails at boot, as
   [the RNG section](platform-proxmox.md#do-give-enterprise-linux-guests-a-virtio-rng)
   explains:

   ```bash
   qm set VMID --rng0 source=/dev/urandom
   ```

5. **Attach the file as vendor data**, and look at what Proxmox will send:

   ```bash
   qm set VMID --cicustom "vendor=local:snippets/onboard-new-vm.yaml"
   qm cloudinit dump VMID user
   ```

   ```text
   #cloud-config
   hostname: NAME
   manage_etc_hosts: true
   fqdn: NAME
   user: ADMIN
   ssh_authorized_keys:
     - ssh-ed25519 AAAA...
   chpasswd:
     expire: False
   users:
     - default
   package_upgrade: true
   ```

   The dump is Proxmox's own user data, unchanged by the snippet: your
   administrator, key and hostname. Its `users:` list is the one that replaces
   the file's, which is why the file creates `svc_ansible` in its script here.
   `package_upgrade: true` makes the first boot install every pending update,
   which can take several minutes; `qm set VMID --ciupgrade 0` turns that off.

   Do not use `user=` in place of `vendor=`. That replaces Proxmox's user data
   with the file: the administrator, its key and the hostname from the panel
   then never reach the VM, and you cannot log in to it.

6. **Start the VM and watch its console.** cloud-init prints the `onboard:`
   lines on the serial console near the end of the first boot, so attach right
   after the start; press Ctrl-O to leave the console:

   ```bash
   qm start VMID
   qm terminal VMID
   ```

   ```text
   [   83.041046] cloud-init[1026]: onboard: created svc_ansible here, because the users: list of this file was not applied
   [   83.108933] cloud-init[1026]: onboard: svc_ansible is ready; set its sudo password next
   [   83.116552] cloud-init[1026]: onboard: Add this VM on the controller: in the guide's folder, run
   [   83.116766] cloud-init[1026]: onboard:   sudo bash controller/add-target.sh --from-info
   [   83.116887] cloud-init[1026]: onboard: then paste these lines and press Ctrl-D:
   [   83.117215] cloud-init[1026]: onboard: name=NAME
   [   83.117352] cloud-init[1026]: onboard: address=VM_ADDRESS
   [   83.117427] cloud-init[1026]: onboard: group=ubuntu
   [   83.117498] cloud-init[1026]: onboard: fingerprint=SHA256:...
   ```

   The console also shows the VM's address and, between
   `-----BEGIN SSH HOST KEY FINGERPRINTS-----` lines, its host-key
   fingerprints; the `(RSA)` one equals the `fingerprint=` value. The console
   has no scrollback: if you attached too late, read the log on the VM as the
   check below shows.

**For many VMs, set this on a template.** Make one VM as above, do not start
it, and convert it to a template with `qm template VMID`. Every clone keeps
the `--cicustom` setting and prepares itself at its own first boot. Give each
clone its own name, and its own address if you use fixed ones, before you
start it.

**After the first boot, leave the VM's cloud-init settings alone.** A change
to the administrator, key, name, search domain or network gives the VM a new
instance ID. At its next boot cloud-init then treats it as a new machine: it
creates **new SSH host keys** and runs the file again. The account and its
password stay as they were, but the controller sees a changed host key, and
Stage 4's
[rebuild steps](stage-4-add-target-first-job.md#do-rebuild-or-retire-a-target)
apply. Editing the snippet alone changes nothing on a VM that has booted. To
change a VM that exists, use [Stage 2](stage-2-existing-machines.md).

## Do: on another hypervisor, build a NoCloud seed

**Where: any Linux machine that holds the filled copy, such as your
workstation or the controller.**

Without Proxmox's cloud-init drive, give cloud-init a small ISO with the
volume label `cidata`, which its NoCloud source reads. It holds three files:
`meta-data`, which names the instance; `user-data`, which is yours, with the
VM's name and your administrator's key; and `vendor-data`, which is the
filled copy, unchanged. Replace `NAME` and the key line with your own:

```bash
mkdir -p ~/seed-NAME
cd ~/seed-NAME
cp ~/onboard-new-vm.yaml vendor-data
printf 'instance-id: %s\nlocal-hostname: %s\n' NAME-1 NAME > meta-data
cat > user-data <<'USERDATA'
#cloud-config
hostname: NAME
fqdn: NAME.lab.example
ssh_authorized_keys:
  - ssh-ed25519 AAAA... you@workstation
USERDATA
xorriso -as mkisofs -output ~/seed-NAME.iso -volid cidata -joliet -rock user-data meta-data vendor-data
```

The top-level `ssh_authorized_keys` belongs to the image's default user, which
becomes your administrator: `ubuntu`, `almalinux`, `rocky` or `cloud-user`.
This `user-data` has no `users:` list, so the file's own list applies, and
with it `svc_ansible`.

`genisoimage` takes the same options as `xorriso -as mkisofs`, and
`cloud-localds` from Ubuntu's `cloud-image-utils` package builds the same ISO:

```bash
cd ~/seed-NAME
genisoimage -output ~/seed-NAME.iso -volid cidata -joliet -rock user-data meta-data vendor-data
cloud-localds --vendor-data vendor-data ~/seed-NAME.iso user-data meta-data
```

Attach `seed-NAME.iso` to the new VM as a CD/DVD drive before its first
boot, with your platform's own tools, and boot it. The `instance-id` must be
new for each VM: cloud-init runs the file again only for an instance ID it
has not seen. Detach the ISO once the VM has booted; it holds no secret, but
it is not needed again.

If your `user-data` has its own `write_files:` or `runcmd:`, it replaces the
file's, and the VM is not prepared; the log then has no `onboard:` line. Put
your own first-boot steps in other cloud-init keys, or prepare such a VM with
[Stage 2](stage-2-existing-machines.md) instead.

## Azure: custom data

On Azure the same file is the VM's **custom data**:
[`platforms/azure/targets.yml`](../platforms/azure/targets.yml) fills in the key
and creates the VMs, or you paste the filled copy into the portal, as
[the Azure page](platform-azure.md#paste-it-into-the-portal-instead) shows.

## Check: read what cloud-init printed

**Where: the VM's console, or the VM over SSH as its administrator.**

First wait for cloud-init to finish:

```bash
cloud-init status --wait
```

```text
status: done
```

`status: error` means a check failed; the lines below say which. Then read the
file's own lines from cloud-init's output log:

```bash
sudo grep 'onboard:' /var/log/cloud-init-output.log
```

```text
onboard: svc_ansible is ready; set its sudo password next
onboard: Add this VM on the controller: in the guide's folder, run
onboard:   sudo bash controller/add-target.sh --from-info
onboard: then paste these lines and press Ctrl-D:
onboard: name=lab-ubuntu
onboard: address=VM_ADDRESS
onboard: group=ubuntu
onboard: fingerprint=SHA256:...
```

Copy the `onboard: name=`, `address=`, `group=` and `fingerprint=` lines, or
the whole output: `add-target.sh --from-info` reads a line that ends with
`onboard: ` and one of the four keys with its value, and ignores every other
line. The serial console and the journal put a stamp such as
`[   83.117215] cloud-init[1026]: ` before `onboard:`; lines copied from there
work as they are.

The `fingerprint=` value is what Stage 4 trusts when it scans the VM, so read
it through a channel that does not depend on the VM's SSH host key: the
hypervisor's console. On Proxmox that is `qm terminal VMID` or the VM's
**Console** in the web UI, as
[reading a VM's console](platform-proxmox.md#do-read-a-vms-console-and-host-key-fingerprint-from-the-node)
shows. Over SSH as the administrator, `cloud-init status` and the log are fine
for everything else; compare the fingerprint with the console once.

Two values can be missing on purpose:

- **No `name=` line**, and the file says
  `onboard: and add --name with the name the inventory should use`: the VM's
  short hostname is one the inventory reserves (`localhost`, `all`,
  `ungrouped`, `lab`, `ubuntu`, `enterprise_linux`) or is not a plain name.
  This happens with a cloud image's default name, or on Enterprise Linux
  without `fqdn`. Stage 4 then asks for `--name`.
- **No `address=` line**, and it says
  `onboard: and add --address with the address the controller reaches`: the
  VM has no global IPv4 address, or more than one, and the file does not know
  which one the controller uses. Stage 4 then asks for `--address`.

To print the values again later, run
[`onboard/inventory-info.sh`](../onboard/inventory-info.sh) on the VM with
`sudo sh inventory-info.sh`, as
[Stage 2](stage-2-existing-machines.md#do-read-a-prepared-vms-values-again)
shows. It leaves nothing out: when it cannot choose a name or an address it
stops with `INFO FAILED` and names the setting at its top to fill in.

## Do: set the sudo password

cloud-init sets none, on purpose: the file is meant to be the same for every
VM and to carry no secret, user data can be read back on the platform and on
the VM, and Azure advises against secrets in custom data. Do not add one to
the file: the account is created with a locked password field. Until you
set a password, `svc_ansible` can log in with its key but cannot use sudo, and
every template except Ping fails.

Choose the password now; the guide's default is **one shared sudo password
for all lab targets**, at least 12 characters, which Stage 4 stores once in
Semaphore. **Save the plain password in your password manager now**: Stage 4
needs it, and so does any later recovery. Then set it in one of these ways,
simplest first.

**a. As the VM's administrator, on its console or over SSH:**

```bash
sudo passwd svc_ansible
sudo getent shadow svc_ansible | cut -d: -f2 | cut -c1
```

`passwd` asks for the new password twice. Setting a new password as root
writes a fresh hash over the locked field, so no separate unlock is needed.
The second command prints only the first character of the stored field: `$`
means a password is set; `!` or `*` means the account is still locked or has
none. The same test is what `inventory-info.sh` reports as `password set`.
The password works for sudo only: the SSH drop-in still admits `svc_ansible`
by key alone.

**b. With the Stage 2 onboarding script and a hash.** Make a hash as
[Stage 2](stage-2-existing-machines.md#do-choose-a-sudo-password-and-make-its-hash)
shows and run `onboard-linux.sh` with it, as
[running it over SSH](stage-2-existing-machines.md#do-run-the-onboarding-script-over-ssh)
shows. The script is safe to run on a VM that cloud-init prepared: it finds
the account, key, sudo rule and drop-in in place, reports them `unchanged`,
and sets the password. Give it the same service key, because it replaces the
account's authorized keys with exactly the keys you give it.

**c. With the bootstrap playbook from the controller**, when the controller
can log in as the VM's administrator:
[Stage 2](stage-2-existing-machines.md#do-let-the-controller-do-it-with-the-bootstrap-playbook).
On a VM that cloud-init prepared, it sets the password you type at its prompt
and checks what cloud-init wrote. It prints a whole `add-target.sh` command
rather than lines.

**d. On Azure, with Run Command**, without any SSH path:
[set the sudo password without SSH](platform-azure.md#set-the-sudo-password-without-ssh).

## Save these values

| Value | Where it came from | Needed in |
| --- | --- | --- |
| The `name=`, `address=`, `group=` and `fingerprint=` lines | The console or `/var/log/cloud-init-output.log` on the VM | [Stage 4](stage-4-add-target-first-job.md#do-add-the-target-with-add-targetsh) |
| A `--name` or `--address` value, if a line was left out | You choose the name; the address is the one the controller reaches | Stage 4, as the option it asks for |
| The plain sudo password | You chose it in the last step | [Stage 4](stage-4-add-target-first-job.md#do-give-semaphore-the-sudo-password), and recovery |
| `~/onboard-new-vm.yaml` | The first step, on the controller | Every new VM this controller manages |
| The VM's ID, administrator name and administrator key | Your platform and the VM's settings | Console access and recovery |

## When it fails

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| `cloud-init status` says `error`, and the log has `onboard: ERROR: svc_ansible has no valid public key; was the placeholder replaced?` | The placeholder was not replaced, or the file did not reach cloud-init as written | Check the filled copy as in the first step. cloud-init does not run again: create the VM again, or prepare it with [Stage 2](stage-2-existing-machines.md). |
| No `onboard:` line at all in the log | The VM never received the file: wrong snippet path or storage, no `cidata` label, an installer ISO instead of a cloud image, or user data of your own with a `runcmd:` or `write_files:` that replaced the file's | Compare what the VM got, `sudo cat /var/lib/cloud/instance/vendor-data.txt` (and `user-data.txt`), with your file; on Proxmox, `qm config VMID` shows the `cicustom` line. Then create the VM again, or use Stage 2. |
| `onboard: ERROR: ...` naming sudo, SSH, a key type or `AllowUsers` | The image's own configuration conflicts with the account's rules | Fix what it names, then run the Stage 2 script on the VM; it repeats every check. |
| `Match rules depend on the client's address` | The image's SSH configuration has `Match Address` or similar rules | Run the Stage 2 script with `CONTROLLER_ADDRESS` set, so it checks the real address. |
| `onboard: and add --name ...` or `--address ...` | A reserved or default hostname, no `fqdn` on Enterprise Linux, or several addresses | Give that option in Stage 4; nothing is wrong with the VM. |
| You cannot log in as the administrator | The administrator and key never reached the VM: on Proxmox, the file was attached with `user=` in place of `vendor=`, or the VM has no `--ciuser` and `--sshkeys` | Create the VM again with the file as vendor data and the administrator in the VM's own settings. |
| After a change to the VM's cloud-init settings, Stage 4 or Ping reports a changed host key | The change gave the VM a new instance ID, and cloud-init made new host keys at the next boot | Read the new `fingerprint=` line and follow Stage 4's [rebuild steps](stage-4-add-target-first-job.md#do-rebuild-or-retire-a-target). |
| `systemctl --failed` lists `rngd.service` on Enterprise Linux | The VM has no hardware random number device | Add a VirtIO RNG and stop and start the VM from the hypervisor, as the [Proxmox page](platform-proxmox.md#do-give-enterprise-linux-guests-a-virtio-rng) shows. |
| `onboard: apt-get update failed` or `python3-dnf installation failed` | The VM cannot reach its package repositories, or RHEL is not registered | Fix the VM's network or registration, then run the Stage 2 script. |
| Stage 4's templates fail with `Missing sudo password` or `Incorrect sudo password` | No password set on the VM, or Semaphore holds another one | [Set the sudo password](#do-set-the-sudo-password) and check Semaphore's copy in Stage 4. |

## Concept

cloud-init is the image's own first-boot agent. It reads its data from
whatever source the platform offers (Proxmox's cloud-init drive, a NoCloud ISO,
Azure's custom data) and runs it once per instance. User data is the
operator's; vendor data is a second document that cloud-init merges under it,
where user data wins any key both define. That is why the file works beside
Proxmox's own user data, and why it creates the account in its script when
its `users:` list loses. That is why one file can
prepare a VM on any of them, and why it does nothing for a VM that has already
booted. The VM then prints data, not a command: the controller does not trust
the VM, so only `add-target.sh`, reviewed code on the controller, acts on those
values, as
[Stage 4](stage-4-add-target-first-job.md#why-the-vm-prints-lines-not-a-command)
explains.

## Next

[Stage 4: add the target and run the first job](stage-4-add-target-first-job.md).
