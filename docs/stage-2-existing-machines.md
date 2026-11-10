# Stage 2: onboard a machine that already exists

[Back to the guide](../README.md) · [Previous: Stage 1, the controller](stage-1-controller.md) · [Next: Stage 4, add the target and run the first job](stage-4-add-target-first-job.md)

This stage is for a Linux machine that is already installed and running. For
a VM you are about to create, [Stage 3](stage-3-new-vms-cloud-init.md) prepares
it at first boot instead; both stages end at the same place and hand off to
Stage 4. Do this stage once per machine.

## Goal

The machine has the automation account `svc_ansible`, which logs in with the
controller's service key only and uses sudo with its own password. You have
the four lines the controller needs, `name=`, `address=`, `group=` and
`fingerprint=`, and you know the sudo password you gave the account.

## Before you start

- **The service key copy.** Stage 1 ends with a copy of the service key in your
  home folder on the controller, `~/svc_ansible.pub`. If it is missing, make it
  again on the controller with
  `sudo cat /etc/semaphore/svc_ansible.pub > ~/svc_ansible.pub`; it is one
  line that starts with `ssh-rsa`.
- **The guide's folder** on the controller, `~/ansible-semaphore-guide`, from
  Stage 1. The commands below that run on the controller start there.
- **A way to get root on the machine:** an administrator account you can log in
  to over SSH or at the machine's console, whose `sudo` works.
- **A supported system.** The onboarding script and the playbook accept Ubuntu
  24.04, and AlmaLinux, Rocky Linux or RHEL 9. Any other system stops them
  before they change anything. RHEL must be registered if a package the account
  needs is missing, because they install it from the system's repositories:
  `python3`, `sudo` and `openssh-server` everywhere, `python3-apt` on Ubuntu,
  `python3-dnf` and `python3-libselinux` on Enterprise Linux.
- **The controller's IP address,** which `hostname -I` prints on the
  controller. On a lab with one network it is the only address shown.

Pick one way for this machine:

| You have | Use |
| --- | --- |
| SSH from the controller to the machine as its administrator, with a password or a key | [The onboarding script over SSH](#do-run-the-onboarding-script-over-ssh) |
| Only the machine's console | [The onboarding script from the console](#do-run-the-onboarding-script-from-the-console) |
| SSH from the controller as the administrator with a key, its host key pinned, and you prefer Ansible | [The bootstrap playbook](#do-let-the-controller-do-it-with-the-bootstrap-playbook) |
| An Azure VM and no SSH path yet | [Run Command](platform-azure.md#do-onboard-an-existing-vm-with-run-command) on the Azure page |

Every way makes the same changes and is safe to run again. Doing the same by
hand, step by step, is [SSH, sudo and the automation account by hand](manual-access.md).

## Do: choose a sudo password and make its hash

**Where: the controller, as your administrator account.**

`svc_ansible` uses sudo with its own password. Choose that password now: at
least 12 characters, because the bootstrap playbook refuses a shorter one. Use
**one shared sudo password for every lab target**. Semaphore then needs it
only once, as one credential, in Stage 4. Separate passwords per target are
possible, but they need Ansible Vault; Stage 4 shows both.

**Save the plain password in your password manager now.** Stage 4 needs it
again, in Semaphore's Key Store, and you need it to use sudo as `svc_ansible`
at the machine's console. Nothing in the guide can show it to you again.

The onboarding script never takes the password itself, only a SHA-512 hash of
it. `openssl` makes one; it asks for the password twice and shows nothing:

```bash
openssl passwd -6
```

It prints one line that starts with `$6$`. The hash cannot be turned back into
the password, but it can be attacked offline, so keep it out of notes, chat
and shared files. You can make it on any Linux machine with OpenSSL. The two
script ways below make it on the target itself, as part of the run, so that you
never copy it; use the line printed here when you edit the script's constants
instead, or for [Run Command](platform-azure.md#do-onboard-an-existing-vm-with-run-command).
The bootstrap playbook needs no hash: it asks for the password.

A script run without a hash keeps the account's existing password; a new
account then has none, its output says `password: NOT SET`, and sudo waits
until you run it again with a hash.

## Do: pin the VM's host key on the controller

**Where: the machine's console, then the controller as your administrator
account.** Do this before the first SSH connection from the controller to the
machine, for the SSH and playbook ways. It makes sure that the machine you
reach over the network is the one you see at its console, so that what it
prints over SSH, the fingerprint included, can be trusted.

At the machine's console, logged in as its administrator, read the RSA host
key's fingerprint. On Proxmox, the node can open that console, as
[the Proxmox page](platform-proxmox.md#do-read-a-vms-console-and-host-key-fingerprint-from-the-node)
shows:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub
```

```text
3072 SHA256:... root@HOSTNAME (RSA)
```

On the controller, connect to the **address you will use for the machine from
now on** and ask for its RSA key:

```bash
ssh -o HostKeyAlgorithms=rsa-sha2-512,rsa-sha2-256 ADMIN@VM_ADDRESS
```

SSH shows `RSA key fingerprint is SHA256:...` and asks whether to continue.
Answer `yes` only when the value matches the console's, character for
character. A different value means another machine answers at that address:
stop and find out why. SSH saves the key in `~/.ssh/known_hosts` before it
tries to log in, so the pin holds even when the login itself fails. Check it:

```bash
ssh-keygen -F VM_ADDRESS -f ~/.ssh/known_hosts
```

It prints the saved line. Later SSH and Ansible runs to that same address
check the key against it and stop on a mismatch. A DNS name and an IP address
are different entries: use the same one everywhere.
[Manual access, step 2](manual-access.md#step-2-authenticate-each-targets-host-key)
explains the same check.

## Do: run the onboarding script over SSH

**Where: the controller, then the machine, as its administrator.** Use this
when you can log in from the controller to the machine as its administrator,
with a password or a key. Pin its host key first, as the previous section
shows.

On the controller, copy the script and the service key to the administrator's
home folder on the machine, then log in:

```bash
cd ~/ansible-semaphore-guide
scp onboard/existing/onboard-linux.sh ~/svc_ansible.pub ADMIN@VM_ADDRESS:
ssh ADMIN@VM_ADDRESS
```

If `scp` says `Permission denied (publickey)`, the administrator accepts only
another machine's key, such as your workstation's; see
[manual access, step 3](manual-access.md#step-3-prepare-a-dedicated-target-account)
for two ways around it, or use the console way below.

Now, on the machine, in that SSH session, open a root shell. `sudo -s` keeps
you in the home folder that holds the two files:

```bash
sudo -s
```

In the root shell, give the script its three inputs as environment variables
and run it. The first line asks twice for the sudo password you chose and
saves only its hash; replace `CONTROLLER_IP` with the controller's IP address:

<!-- VERIFY-LIVE: run this exact block in a root shell from `sudo -s` on Ubuntu 24.04, AlmaLinux 9, Rocky Linux 9 and RHEL 9 targets; check that `openssl passwd -6` prompts inside $(...), that the output says `password: set from PASSWORD_HASH`, and that openssl is present on a minimal install of each -->
```bash
ONBOARD_PASSWORD_HASH=$(openssl passwd -6) && export ONBOARD_PASSWORD_HASH
export ONBOARD_PUBLIC_KEYS="$(cat svc_ansible.pub)"
export ONBOARD_CONTROLLER_ADDRESS=CONTROLLER_IP
bash onboard-linux.sh
```

If `openssl` prints `Verify failure`, the two entries differed: run the first
line again. To use the hash you made on the controller instead, replace the
first line with `read -r ONBOARD_PASSWORD_HASH && export ONBOARD_PASSWORD_HASH`
and paste the hash at the empty prompt.

The script reads `ONBOARD_PUBLIC_KEYS`, `ONBOARD_PASSWORD_HASH` and
`ONBOARD_CONTROLLER_ADDRESS` when they are set, in place of the constants at
its top, so your copy needs no editing. `ONBOARD_PUBLIC_KEYS` becomes the
account's whole list of authorized keys. To run the
[command-line lessons](05-cli-lessons.md) with a key of your own as well, copy
that public key over too and list both:
`export ONBOARD_PUBLIC_KEYS="$(cat svc_ansible.pub ansible_lab.pub)"`.
`ONBOARD_CONTROLLER_ADDRESS` must be an IP address. It lets the script check
the SSH policy for connections from the controller, which it requires when the
SSH configuration has `Match` rules that depend on the client's address, and it
picks the `address=` line from the route to the controller. Empty, the script
checks from loopback and prints `address=` only for a machine with exactly one
IPv4 address.

The hash stays in the root shell's environment and never appears in a command
line, so other accounts cannot see it in the process list, and it is not in
the shell history. A one-line form such as
`sudo env ONBOARD_PASSWORD_HASH='HASH' ... bash onboard-linux.sh` also works,
but needs the single quotes around the hash, and shows the hash to every
account on the machine in the process list while the script runs.

The output ends like this; the values are this machine's:

```text
host: HOSTNAME (AlmaLinux 9.6 (Sage Margay))
packages: present
account: svc_ansible created; authorized keys replaced:
  4096 SHA256:... ansible-practice (RSA)
password: set from PASSWORD_HASH
sudo: /etc/sudoers.d/90-ansible-lab written; svc_ansible's own password is required
ssh: /etc/ssh/sshd_config.d/70-ansible-lab.conf written; sshd.service active; key only for svc_ansible, checked from CONTROLLER_IP to 1 local address and port pair(s)
host keys to compare with ssh-keyscan from the controller:
  256 SHA256:... (ECDSA)
  256 SHA256:... (ED25519)
  3072 SHA256:... (RSA)
Add this VM on the controller: in the guide's folder, run
  sudo bash controller/add-target.sh --from-info
then paste these lines and press Ctrl-D:
name=HOSTNAME
address=VM_ADDRESS
group=enterprise_linux
fingerprint=SHA256:...
RESULT: OK
```

On Ubuntu the group is `ubuntu`. `RESULT: OK` is always the last line; on any
problem the last line is `RESULT: FAILED:` with the reason, and the script has
changed nothing that could lock you out. A value the machine cannot read, such
as a hostname the inventory reserves or an address when it has several, is
left out, and a line `and add --name ...`, `--address ...` or
`--fingerprint ...` above the values names the option that supplies it in
Stage 4. **Copy the four lines from `name=` to `fingerprint=`** to a scratch
file on the controller or to your notes; they are public values. The
`fingerprint=` line must equal the console value you compared when you pinned
the host key.

Leave the root shell, which also forgets the hash, and delete the copies:

```bash
exit
rm onboard-linux.sh svc_ansible.pub
```

Then log out of the machine with `exit`.

### Alternative: edit the constants

The script also works with its constants edited, as its comments describe.
On the controller, make a private copy, edit it, and copy it over:

```bash
cd ~/ansible-semaphore-guide
install -m 0600 onboard/existing/onboard-linux.sh ~/onboard-linux.sh
"${EDITOR:-nano}" ~/onboard-linux.sh
scp ~/onboard-linux.sh ADMIN@VM_ADDRESS:
```

In the editor, replace the line `REPLACE_WITH_AUTOMATION_PUBLIC_KEY` with the
contents of `~/svc_ansible.pub`, keeping the two `END_OF_KEYS` lines; put the
hash from `openssl passwd -6` between the single quotes of
`PASSWORD_HASH=''`; and put the controller's IP address between the quotes of
`CONTROLLER_ADDRESS=''`. The keys are read through a quoted here-document, so
a key comment is stored as text and never run. On the machine, run
`sudo bash onboard-linux.sh`, then `rm onboard-linux.sh`. Delete
`~/onboard-linux.sh` on the controller too: both copies hold the hash.

## Do: run the onboarding script from the console

**Where: the machine's console, logged in as its administrator.** Use this
when the controller cannot reach the machine over SSH. The script is over 500
lines, far too long to type, and pasting that much into a web console is
impractical, so the machine fetches it itself.

**Get the script.** If the machine can reach GitHub over HTTPS, download the
file of the exact commit your controller's copy comes from. On the controller,
print that commit and the file's checksum:

```bash
git -C ~/ansible-semaphore-guide rev-parse HEAD
sha256sum ~/ansible-semaphore-guide/onboard/existing/onboard-linux.sh
```

At the machine's console, with `COMMIT` replaced by the 40 characters
`git` printed:

<!-- VERIFY-LIVE: raw.githubusercontent.com serves the file by full commit hash once the release is pushed; curl is present on minimal Ubuntu 24.04 and EL9 installs -->
```bash
curl -fsSLO https://raw.githubusercontent.com/kevo099/ansible-semaphore-guide/COMMIT/onboard/existing/onboard-linux.sh
sha256sum onboard-linux.sh
```

Run the script only when both checksums are the same. If the machine can reach
the controller's SSH port instead, copy the file and the key from the
controller's administrator's home folder, checking the controller's host key
when `scp` asks:

```bash
scp ADMIN@CONTROLLER_IP:ansible-semaphore-guide/onboard/existing/onboard-linux.sh .
scp ADMIN@CONTROLLER_IP:svc_ansible.pub .
```

**Supply the key.** The service key is one line of about 740 characters. Paste
it into a file, then press Enter and Ctrl-D:

```bash
cat > svc_ansible.pub
```

Check it against the controller's copy: `ssh-keygen -lf svc_ansible.pub` on the
machine and `ssh-keygen -lf ~/svc_ansible.pub` on the controller must print
the same `SHA256:` value. A console that shows the screen as a picture may not
paste at all; then copy the key with `scp` as above, or use the SSH way.

<!-- VERIFY-LIVE: Proxmox: does the default noVNC console paste text into a text-mode Linux console? Does the xterm.js console or qm terminal (VM with serial0: socket and a getty on ttyS0) paste a 740-character line intact and allow copying the output? -->
On Proxmox, a VM's serial console, in the web UI's **Console** (xterm.js) or
with `qm terminal VMID` on the node, copies and pastes text like a terminal,
while the graphical **noVNC** console is a picture of the screen;
[the Proxmox page](platform-proxmox.md#do-read-a-vms-console-and-host-key-fingerprint-from-the-node)
shows it.

**Run it.** Open a root shell and run the same block as the SSH way:

```bash
sudo -s
```

```bash
ONBOARD_PASSWORD_HASH=$(openssl passwd -6) && export ONBOARD_PASSWORD_HASH
export ONBOARD_PUBLIC_KEYS="$(cat svc_ansible.pub)"
export ONBOARD_CONTROLLER_ADDRESS=CONTROLLER_IP
bash onboard-linux.sh
```

```bash
exit
rm onboard-linux.sh svc_ansible.pub
```

**Read the result.** The output ends with the lines shown in the SSH way, and
`RESULT: OK` last. A graphical console does not let you copy them: write down
the four values instead. You can avoid typing the fingerprint: on the
controller, `ssh-keyscan -t rsa VM_ADDRESS 2>/dev/null | ssh-keygen -lf -`
prints the fingerprint of the key the network offers. When it matches the
console's `fingerprint=` value character for character, copy it from the
controller's terminal. If it differs, stop: another machine answers at that
address. In Stage 4 a wrong fingerprint is refused, never trusted.

## Do: let the controller do it with the bootstrap playbook

**Where: the controller, as your administrator account, in the guide's
folder.** [`bootstrap-existing-vm.yml`](../onboard/existing/bootstrap-existing-vm.yml)
does what the script does, from the controller, over SSH as the machine's
administrator. Instead of data lines it ends with a whole `add-target.sh`
command, which it builds on the controller.

It needs:

1. **The machine's host key pinned** in your `~/.ssh/known_hosts`, as
   [pin the VM's host key](#do-pin-the-vms-host-key-on-the-controller) shows.
   The guide's `ansible.cfg` sets `StrictHostKeyChecking=yes`, so an unpinned
   host stops the run with `Host key verification failed`.
2. **Key login as the machine's administrator.** Ansible cannot type an SSH
   password here: its `-k` option needs `sshpass`, which the installer does
   not install. If the administrator has only a password, install a key of
   yours for it, once. Create the key on the controller if you have none,
   then copy its public half; `ssh-copy-id` asks for the administrator's
   password one last time:

   ```bash
   test -f ~/.ssh/id_rsa.pub || ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa
   ssh-copy-id -i ~/.ssh/id_rsa.pub ADMIN@VM_ADDRESS
   ssh ADMIN@VM_ADDRESS true
   ```

   <!-- VERIFY-LIVE: ssh-copy-id against a fresh ISO-installed Ubuntu 24.04 and EL9 target whose administrator has password SSH only -->
   The last command must finish without asking for a password. If you gave the
   key a passphrase, load it first with `eval "$(ssh-agent -s)"` and
   `ssh-add ~/.ssh/id_rsa`. When the administrator accepts only your
   workstation's key, as on a cloud image, see
   [manual access, step 3](manual-access.md#step-3-prepare-a-dedicated-target-account).
3. **Python 3 on the machine,** which the supported systems have.
4. **An inventory of the machines to prepare.** Copy the example once and
   replace its lines with one line per machine, `NAME ansible_host=VM_ADDRESS`,
   using the address you pinned:

   ```bash
   cd ~/ansible-semaphore-guide
   cp inventories/bootstrap.ini.example inventories/bootstrap.ini
   "${EDITOR:-nano}" inventories/bootstrap.ini
   ```

   The name becomes the machine's inventory name on the controller, so do not
   use `localhost`, `all`, `ungrouped`, `lab`, `ubuntu` or `enterprise_linux`.
   Git ignores `inventories/bootstrap.ini`.

Run it for one machine; `--limit` names it:

```bash
cd ~/ansible-semaphore-guide
/opt/ansible-venv/bin/ansible-playbook -i inventories/bootstrap.ini \
  onboard/existing/bootstrap-existing-vm.yml --limit NAME -u ADMIN -K \
  -e '{"automation_public_key_files": ["~/svc_ansible.pub"]}'
```

`-K` makes Ansible ask for the administrator's own sudo password, as
`BECOME password:`. Leave it out when that administrator's sudo needs no
password, as on most cloud images. Keep the `-e` option exactly as shown:
without it the playbook authorizes `~/.ssh/ansible_lab.pub` in place of the
service key, and Semaphore could no longer log in. If you also use a key of
your own for the command-line lessons, list both:
`["~/svc_ansible.pub", "~/.ssh/ansible_lab.pub"]`.

The playbook then asks for the new sudo password for `svc_ansible`, twice:

```text
BECOME password:
New sudo password for svc_ansible on this host (unique per target):
confirm New sudo password for svc_ansible on this host (unique per target):
```

Type the password you chose and saved; with one shared lab password, that is
the same password for every machine, whatever the prompt says. It refuses a
password shorter than 12 characters, a run without `--limit` or with several
hosts, and an unsupported system. It checks the SSH configuration before it
reloads SSH and puts the previous state back when a check fails. Near the end
it prints:

```text
TASK [Show the controller command that adds this host] *************************
ok: [NAME] => {
    "msg": [
        "Add this VM on the controller: in the guide's folder, run this command (replace NAME, ADDRESS or FINGERPRINT if shown, and add --lab-dir DIR for a lab folder other than /opt/ansible-lab):",
        "sudo bash controller/add-target.sh --name NAME --address VM_ADDRESS --group enterprise_linux --fingerprint SHA256:..."
    ]
}
```

and a `PLAY RECAP` with `failed=0`. **Copy that whole `sudo bash
controller/add-target.sh ...` command** to your notes: it is the one command in
the guide you may run as printed, because the controller built it from its own
inventory and a fingerprint read over the SSH session you pinned. Where it
shows `NAME`, `ADDRESS` or `FINGERPRINT` in capitals, the value did not pass
its check; replace it with a value you read yourself. A second run with the
same password reports no changes.

## Do: read a prepared VM's values again

**Where: the machine, as its administrator.** When you no longer have the four
lines, for example after cloud-init prepared the machine, or after a restore,
[`inventory-info.sh`](../onboard/inventory-info.sh) prints them again. It
changes nothing: it reads the hostname, system, IPv4 addresses and RSA host
key, and reports the state of `svc_ansible`, its password and the sudo
configuration. Copy it to the machine as you copied the onboarding script,
over SSH with `scp` or from the console with `curl`, using the path
`onboard/inventory-info.sh`, then run it with root rights, which it needs to
read the account's password state:

```bash
sudo sh inventory-info.sh
rm inventory-info.sh
```

It has three constants at its top, which you edit before running it when
needed; it reads no environment variables:

- `CONTROLLER_ADDRESS`: the controller's IP address. Set, the printed address
  is the one this machine uses to reach the controller. Empty, the machine
  must have exactly one global IPv4 address.
- `TARGET_ADDRESS`: an address of this machine to print, chosen by you.
- `INVENTORY_NAME`: the inventory name; empty, the short hostname. A name the
  inventory reserves, such as `localhost`, `lab` or `ubuntu`, is refused.

It never leaves a value out. It either prints all four lines, after a short
summary, or stops with `INFO FAILED:` and names the constant to fill in:

```text
VM: NAME | VM_ADDRESS | almalinux 9.6
RSA: SHA256:...
SSH keys present; password set; sudo syntax OK
Inventory setup only; access still needs Ping/sudo testing.
Add this VM on the controller: in the guide's folder, run
  sudo bash controller/add-target.sh --from-info
then paste these lines and press Ctrl-D:
name=NAME
address=VM_ADDRESS
group=enterprise_linux
fingerprint=SHA256:...
```

A summary with `WARNING:` means the account is not finished: run the
onboarding again. To read only the fingerprint at a console, one line is
enough:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub
```

## Check

On the machine, the script's first run shows:

```text
password: set from PASSWORD_HASH
sudo: /etc/sudoers.d/90-ansible-lab written; svc_ansible's own password is required
RESULT: OK
```

Running it again with the same inputs is a good check: it reports
`authorized keys unchanged`, `password: unchanged`, and `unchanged` for the
sudo rule and the SSH drop-in, then the same four lines. `password: kept` means it
kept a password set earlier; `NOT SET` means there is none yet. After the
bootstrap playbook, its recap shows `failed=0`, and a repeat run `changed=0`.
At the machine's console, `sudo -l -U svc_ansible` lists `(ALL : ALL) ALL`
without `NOPASSWD`. Whether the controller can log in and use sudo is
checked in Stage 4, by Ping and Baseline preview.

## Save these values

| Value | Where it came from | Needed in |
| --- | --- | --- |
| The `name=`, `address=`, `group=` and `fingerprint=` lines | The end of the script's output, or `inventory-info.sh` | Stage 4, pasted into `add-target.sh --from-info` |
| The whole `sudo bash controller/add-target.sh ...` command | The end of the bootstrap playbook's output | Stage 4, run as printed |
| The plain sudo password of `svc_ansible` | You chose it; saved in your password manager | Stage 4, Semaphore's Key Store; console recovery |
| The address you pinned | Your choice, the same everywhere | Stage 4 and every later SSH run |

## When it fails

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| The last line is `RESULT: FAILED: ...` | The message names it: a key this SSH server refuses, a `NOPASSWD` rule, an SSH setting that overrides the account's, an unsupported system | Fix what it names and run the script again. It restored the previous SSH and sudo state before stopping. |
| `RESULT: FAILED: run as root; Azure Run Command already does` | The script ran without root rights | Run it from the `sudo -s` root shell, or with `sudo bash onboard-linux.sh`. |
| `RESULT: FAILED: replace REPLACE_WITH_AUTOMATION_PUBLIC_KEY with the controller's public key` | `ONBOARD_PUBLIC_KEYS` was empty, for example because `svc_ansible.pub` was not in the current folder, so the script fell back to its unedited constant | Check with `ls` that the key file is there, export the variable again and rerun. |
| `RESULT: FAILED: PASSWORD_HASH must be a SHA-512 crypt hash ...` | The hash was cut or changed on its way, for example by double quotes that expanded its `$` signs | Make it again with the `openssl` line in the root shell. |
| `RESULT: FAILED: the SSH configuration has Match rules that depend on the client's address ...` | `ONBOARD_CONTROLLER_ADDRESS` was empty | Export it with the controller's IP address and rerun. |
| `RESULT: FAILED: none of the keys can log in to this SSH server ...` | A crypto policy, such as FIPS or a STIG, refuses the key type or its size | Use the RSA 4096 service key the installer made. |
| `password: NOT SET` | No hash was given to a new account | Run the script again with `ONBOARD_PASSWORD_HASH`. |
| `scp` or `ssh` says `Permission denied (publickey)` for the administrator | The administrator accepts another machine's key only | [Manual access, step 3](manual-access.md#step-3-prepare-a-dedicated-target-account), or the console way. |
| `ssh` says `REMOTE HOST IDENTIFICATION HAS CHANGED`, or the playbook says `Host key verification failed` | The address answered with a different key than the pinned one, or no key is pinned for that exact address | Compare with the console value again. Remove an old entry only after you know why it changed: `ssh-keygen -R VM_ADDRESS`. |
| The playbook says `Name one host with --limit` | `--limit` was missing or matched several hosts | Name one host from `inventories/bootstrap.ini`. |
| The playbook stops with `Missing sudo password`, or `-K` was refused | The administrator's sudo asks for a password | Add `-K` and type the administrator's own sudo password. |
| `curl` fails at the console | The machine cannot reach GitHub | Copy the files from the controller with `scp`, or use the SSH way. |
| The checksums differ | The download is not the file your controller has | Do not run it. Check the commit, and download again. |
| `INFO FAILED: Multiple/no IPv4 addresses; ...` from `inventory-info.sh` | The machine has several addresses, or none | Set `CONTROLLER_ADDRESS` or `TARGET_ADDRESS` at the script's top. |

Problems with adding the machine, Ping or sudo in Semaphore are in
[Stage 4](stage-4-add-target-first-job.md#when-a-step-fails).

## Concept

A target needs three things from the controller's point of view: a key that
proves who Ansible is, a pinned host key that proves which machine it reached,
and a sudo password that separately authorizes privileged work. This stage
does the target's side of all three. The account logs in with the service key
only, because its SSH drop-in requires a key, and its sudo always asks for its
own password, because the sudoers rule has no `NOPASSWD`. The scripts check
both before SSH reloads, so a mistake stops the run instead of locking the
account out. What the machine prints is data, not a command:
[Stage 4 explains why](stage-4-add-target-first-job.md#why-the-vm-prints-lines-not-a-command).

## Next

[Stage 4: add the target and run the first job](stage-4-add-target-first-job.md).
