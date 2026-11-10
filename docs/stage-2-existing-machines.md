# Stage 2: onboard a machine that already exists

[Back to the guide](../README.md) · [Previous: Stage 1, the controller](stage-1-controller.md) · [Next: Stage 4, add the target and run the first job](stage-4-add-target-first-job.md)

This stage is for a Linux machine that is already installed and running. For
a VM you are about to create, [Stage 3](stage-3-new-vms-cloud-init.md) prepares
it at first boot instead; both stages end at the same place and hand off to
Stage 4. Do this stage once per machine.

The main way is one command on the controller: it prepares the machine over
SSH and adds it to the lab inventory in the same run, so
[Stage 4](stage-4-add-target-first-job.md) then starts at
[giving Semaphore the sudo password](stage-4-add-target-first-job.md#do-give-semaphore-the-sudo-password).
The other ways on this page do the same preparation by hand, from the console,
with Ansible, or through Azure, and leave the adding to Stage 4.

## Goal

The machine has the automation account `svc_ansible`, which logs in with the
controller's service key only and uses sudo with its own password, and you
know that password. With the one command, the controller's inventory also
lists the machine and trusts its verified host key. With the other ways, you
have the four lines the controller needs, `name=`, `address=`, `group=` and
`fingerprint=`.

## Before you start

- **A disposable lab machine.** The lessons change what they manage: they
  replace the login banner (`/etc/motd`), install and configure the time
  service, take over nginx's whole configuration, install packages, apply
  updates and STIG remediation, and can reboot it. Use a machine you can lose or rebuild, never one that runs
  something you need, and never the controller itself. Keep its console, and a
  snapshot or backup, as a way back that does not depend on SSH.
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
- **For the ways by hand only:** the copy of the service key in your home
  folder on the controller, `~/svc_ansible.pub`, which the installer leaves
  there (on a controller installed earlier, make it with
  `sudo cat /etc/semaphore/svc_ansible.pub > ~/svc_ansible.pub`), and the
  controller's IP address, which `hostname -I` prints on the controller. The
  one command reads both itself.

Pick one way for this machine:

| You have | Use |
| --- | --- |
| SSH from the controller to the machine as its administrator, with a password or a key | [One command from the controller](#do-onboard-it-in-one-command-from-the-controller), the default |
| The same, and you want to run each step yourself, or authorize a key of your own beside the service key | [The onboarding script over SSH](#do-run-the-onboarding-script-over-ssh) |
| Only the machine's console | [The onboarding script from the console](#do-run-the-onboarding-script-from-the-console) |
| SSH from the controller as the administrator with a key, its host key pinned, and you prefer Ansible | [The bootstrap playbook](#do-let-the-controller-do-it-with-the-bootstrap-playbook) |
| An Azure VM and no SSH path yet | [Run Command](#azure-run-command), on the Azure page |

Every way makes the same changes on the machine and is safe to run again.
Doing the same by hand, step by step, is
[SSH, sudo and the automation account by hand](manual-access.md).

## Do: onboard it in one command from the controller

**Where: the controller, as your administrator account, in the guide's
folder. Do not use `sudo` and do not run it as root:** it logs in to the
machine with your own SSH keys and known hosts, and asks for `sudo` itself
where it needs it.

```bash
cd ~/ansible-semaphore-guide
bash controller/onboard-target.sh ADMIN@VM_ADDRESS
```

`ADMIN` is the machine's administrator, and `VM_ADDRESS` the IP address or DNS
name the controller will use for it from now on; that exact address goes into
the inventory. [`controller/onboard-target.sh`](../controller/onboard-target.sh)
copies [`onboard-linux.sh`](../onboard/existing/onboard-linux.sh) and the
service key to a temporary folder on the machine, runs the script there with
`sudo`, removes the folder, and gives the machine's `name=`, `group=` and
`fingerprint=` lines, with the address you typed, to
`sudo bash controller/add-target.sh --from-info`, which checks them and adds
the machine.

It asks, in this order:

1. **Your `sudo` password on the controller**, after
   `Reading the service key /etc/semaphore/svc_ansible.pub, which needs sudo on this controller.`
2. **The shared sudo password for `svc_ansible`**, once for the whole run:

   ```text
   The sudo password that svc_ansible gets on these machines: one shared lab password,
   which Semaphore needs once afterwards. Save it in your password manager.
   Sudo password for svc_ansible, 12 characters or more:
   The same password again:
   ```

   Use **one shared sudo password for every lab target**, at least 12
   characters; Semaphore then needs it only once, in Stage 4. **Save it in
   your password manager now**: nothing in the guide can show it to you again.
   Nothing is shown as you type. The controller hashes it with `openssl` and
   sends the machine only the SHA-512 hash, in a file the script removes when
   it ends.
3. **SSH's own question about the machine's host key**, the first time your
   account connects to that address. The command prints three lines first:

   ```text
   This account has not connected to VM_ADDRESS before. SSH shows its RSA key fingerprint next.
   Compare it with the machine's console, sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub,
   and answer yes only when they are the same.
   ```

   SSH then shows `RSA key fingerprint is SHA256:...` and asks whether to
   continue. At the machine's console, logged in as its administrator, run
   `sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub`; on Proxmox the node
   can open that console, as
   [the Proxmox page](platform-proxmox.md#do-read-a-vms-console-and-host-key-fingerprint-from-the-node)
   shows. Answer `yes` only when the two values match character for character.
   A different value means another machine answers at that address: answer
   `no`, and find out why. If you pinned the key earlier, as
   [the next section but one](#do-pin-the-vms-host-key-on-the-controller)
   shows, SSH asks nothing.
4. **The administrator's login password**, if that account logs in with a
   password. The three steps on the machine share one connection, so you type
   it once per machine.
5. **The administrator's own `sudo` password on the machine**, as
   `[sudo] password for ADMIN:`, unless its sudo needs none.
6. **Your `sudo` password on the controller** again, when it adds the
   machine, if `sudo` no longer remembers it.

The machine's part ends with the script's output, as in
[the SSH way](#do-run-the-onboarding-script-over-ssh), and `RESULT: OK`. That
output still says to paste its last lines on the controller; here the command
does that for you. The controller's part follows:

```text
Nothing to paste: this command passes those lines on. Adding VM_ADDRESS on this controller, which needs sudo here:
Using name=lab-alma address=VM_ADDRESS group=enterprise_linux fingerprint=SHA256:...
Added lab-alma (VM_ADDRESS) to /opt/ansible-lab/inventories/lab.ini under [enterprise_linux] and trusted its verified host key.

Prepared and in the inventory: ADMIN@VM_ADDRESS
Next: give Semaphore the sudo password once, sudo python3.12 controller/lab-sudo.py,
then run the Ping and Baseline preview templates.
```

The machine is onboarded on its side and in the inventory. Go to
[Stage 4: give Semaphore the sudo password](stage-4-add-target-first-job.md#do-give-semaphore-the-sudo-password);
you do not need `add-target.sh` for it.

**Several machines in one run.** Name each one; the password is asked once and
given to all of them:

```bash
bash controller/onboard-target.sh ADMIN@VM_ADDRESS_1 ADMIN@VM_ADDRESS_2 ADMIN@VM_ADDRESS_3
```

The machines are prepared one after the other, each with its own host-key
question. A machine that fails does not stop the others. The last lines list
both outcomes, and the run then exits with status 1:

```text
Prepared and in the inventory: ADMIN@VM_ADDRESS_1 ADMIN@VM_ADDRESS_3
Not finished: ADMIN@VM_ADDRESS_2
```

**A hostname the inventory reserves.** A machine whose short hostname is
`localhost`, `all`, `ungrouped`, `lab`, `ubuntu` or `enterprise_linux`, or not a
plain name, cannot keep it as its inventory name. Give it one with `--name`,
for one machine per run:

```bash
bash controller/onboard-target.sh ADMIN@VM_ADDRESS --name lab-alma
```

**Keep the existing passwords.** `--keep-password` asks for no password and
leaves each account's password as it is: use it when you run the command again
for a machine whose password you do not want to change, or when you give the
password another way. A new account then has none, the script reports
`password: NOT SET`, and sudo waits until you set one: run the command again
without the option.

**Another lab folder.** If you installed with `--lab-dir DIR`, add the same
`--lab-dir DIR`.

**When it says `Not finished`.** The lines above it, under that machine's
`=== ADMIN@VM_ADDRESS` header, say why:

| Message | What to do |
| --- | --- |
| `Could not log in to ADMIN@VM_ADDRESS.` | SSH's own message above it says why: a wrong name or address, `Permission denied`, a host key you refused, or `REMOTE HOST IDENTIFICATION HAS CHANGED` for a machine that was rebuilt. See [When it fails](#when-it-fails). |
| `The script did not finish on ADMIN@VM_ADDRESS; its last line above says why.` | The last line is `RESULT: FAILED: ...`, or the administrator's `sudo` refused. Fix what it names. |
| `ADMIN@VM_ADDRESS is prepared, but add-target.sh did not add it; its message above says what it needs.` | The machine is ready; only adding it failed. When `add-target.sh` asked for a name, run the command again for that machine alone with `--name NAME`. |

Then run the command again for the unfinished machines only. Running it again
for a machine that is done is safe: the script reports what is unchanged,
`add-target.sh` says `Already present: ...`, and a password you type again is
set again, so type the same one, or pass `--keep-password`.

**A key of your own as well.** The account's authorized keys become exactly
the service key, and any other key is removed. To also log in as `svc_ansible`
with a key of your own, as the [command-line lessons](05-cli-lessons.md) do,
name its public half, and name it again on every later run for that machine:

```bash
bash controller/onboard-target.sh ADMIN@VM_ADDRESS --extra-key ~/.ssh/ansible_lab.pub
```

It needs a terminal: for the password, for SSH's host-key question and for a
`sudo` prompt on the machine. Without one it stops with
`Run it from a terminal to be asked for the sudo password, or pass --keep-password.`;
with `--keep-password` it runs without a terminal only where nothing has to be
asked: a pinned host key, key login, an administrator whose `sudo` on the
machine needs no password, and your own `sudo` on the controller asking for
none.

## Do: choose a sudo password and make its hash

**Where: the controller, as your administrator account.**

`svc_ansible` uses sudo with its own password. Use **one shared sudo password
for every lab target**, at least 12 characters, because the bootstrap playbook
and the script's `--ask-password` refuse a shorter one. Semaphore then needs it
only once, as one credential, in Stage 4. Separate passwords per target are
possible, but they need Ansible Vault; Stage 4 shows both. **Save the plain
password in your password manager now.** Stage 4 needs it again, and you need
it to use sudo as `svc_ansible` at the machine's console.

**Most ways need no hash.** The one command above, and the script's
`--ask-password` in the SSH and console ways below, ask for the password and
make the hash themselves; the bootstrap playbook asks for the password. Make
a hash yourself only for [Run Command](platform-azure.md#do-onboard-an-existing-vm-with-run-command)
and for [a copy of the script with its constants edited](#alternative-environment-variables-or-edited-constants).
`openssl` makes one; it asks for the password twice and shows nothing:

```bash
openssl passwd -6
```

It prints one line that starts with `$6$`. The hash cannot be turned back into
the password, but it can be attacked offline, so keep it out of notes, chat
and shared files.

A script run without a password or a hash keeps the account's existing
password; a new account then has none, its output says `password: NOT SET`,
and sudo waits until you run it again with one.

## Do: pin the VM's host key on the controller

**Where: the machine's console, then the controller as your administrator
account.** The bootstrap playbook needs this before its first connection; the
one command asks SSH's question itself and needs it only if you prefer to
check first. It makes sure that the machine you reach over the network is the
one you see at its console, so that what it prints over SSH, the fingerprint
included, can be trusted.

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

**Where: the controller, then the machine, as its administrator.** This is the
one command's work, done step by step. Use it when you want to see each step,
or to authorize a key of your own beside the service key. Pin the machine's
host key first, as the previous section shows.

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

On the machine, in that SSH session, run the script with its options, with
`CONTROLLER_IP` replaced by the controller's IP address, then delete the
copies:

```bash
sudo bash onboard-linux.sh --keys svc_ansible.pub --ask-password --controller-address CONTROLLER_IP
rm onboard-linux.sh svc_ansible.pub
```

`--ask-password` asks for the sudo password you chose, twice, without echo:

```text
New sudo password for svc_ansible, 12 characters or more:
The same password again:
```

It hashes the password with `openssl` on the machine, so neither the password
nor the hash ever appears in a command line or the shell history. The options:

- `--keys FILE`: the public keys that may log in as `svc_ansible`, one per
  line. They become the account's whole list of authorized keys. To run the
  [command-line lessons](05-cli-lessons.md) with a key of your own as well,
  copy that public key over too and give both in one file:
  `cat svc_ansible.pub ansible_lab.pub > keys.pub`, then `--keys keys.pub`.
- `--ask-password`: ask here for the sudo password and hash it. Leave it out
  to keep the account's existing password.
- `--password-hash-file FILE`: a file holding a hash from `openssl passwd -6`,
  in place of `--ask-password`; the script removes the file when it ends.
- `--controller-address IP`: the controller's IP address as the machine sees
  it. It lets the script check the SSH policy for connections from the
  controller, which it requires when the SSH configuration has `Match` rules
  that depend on the client's address, and it picks the `address=` line from
  the route to the controller. Without it, the script checks from loopback and
  prints `address=` only for a machine with exactly one IPv4 address.

`sudo bash onboard-linux.sh --help` lists them.

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
the host key. Then log out of the machine with `exit`, and add it in
[Stage 4](stage-4-add-target-first-job.md#do-add-the-target-with-add-targetsh).

### Alternative: environment variables or edited constants

The options are the newest way to give the script its three inputs. It still
reads them from the constants at its top, `PUBLIC_KEYS`, `PASSWORD_HASH` and
`CONTROLLER_ADDRESS`, and from the environment variables
`ONBOARD_PUBLIC_KEYS`, `ONBOARD_PASSWORD_HASH` and
`ONBOARD_CONTROLLER_ADDRESS`, which win over the constants; options given on
the command line win over both. Azure Run Command uses the variables. In a
root shell (`sudo -s`) on the machine, the variable form is:

```bash
ONBOARD_PASSWORD_HASH=$(openssl passwd -6) && export ONBOARD_PASSWORD_HASH
export ONBOARD_PUBLIC_KEYS="$(cat svc_ansible.pub)"
export ONBOARD_CONTROLLER_ADDRESS=CONTROLLER_IP
bash onboard-linux.sh
```

If `openssl` prints `Verify failure`, the two entries differed and the script
ran without a hash: run the whole block again. The hash stays in the root
shell's environment and never appears in a command line. A one-line form such
as `sudo env ONBOARD_PASSWORD_HASH='HASH' ... bash onboard-linux.sh` also
works, but needs the single quotes around the hash, and shows the hash to
every account on the machine in the process list while the script runs.

To edit the constants instead, make a private copy on the controller, edit it,
and copy it over:

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

On Proxmox, a VM's serial console is a text terminal: `qm terminal VMID` on
the node pastes the whole key intact and lets you copy the output, and the web
UI's **Console** opens the same serial console (xterm.js) when the VM has one.
The graphical **noVNC** console is a picture of the screen; do not count on
pasting into it;
[the Proxmox page](platform-proxmox.md#do-read-a-vms-console-and-host-key-fingerprint-from-the-node)
shows it.

**Run it** with the same line as the SSH way, then delete the copies:

```bash
sudo bash onboard-linux.sh --keys svc_ansible.pub --ask-password --controller-address CONTROLLER_IP
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
New sudo password for svc_ansible on this host (the lab's shared one, or this target's own):
confirm New sudo password for svc_ansible on this host (the lab's shared one, or this target's own):
```

Type the password you chose and saved: with one shared lab password, the same
one for every machine. It refuses a
password shorter than 12 characters, a run without `--limit` or with several
hosts, and an unsupported system. It checks the SSH configuration before it
reloads SSH and puts the previous state back when a check fails. Near the end
it prints:

```text
TASK [Show the controller command that adds this host] *************************
ok: [lab-alma] => {
    "msg": [
        "Add this VM on the controller: in the guide's folder, run this command (replace NAME, ADDRESS or FINGERPRINT if shown, and add --lab-dir DIR for a lab folder other than /opt/ansible-lab):",
        "sudo bash controller/add-target.sh --name lab-alma --address alma.example.test --group enterprise_linux --fingerprint SHA256:..."
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

## Azure: Run Command

An Azure VM without an SSH path runs the same script through Azure's Run
Command, with the key and the hash as parameters:
[onboard an existing VM with Run Command](platform-azure.md#do-onboard-an-existing-vm-with-run-command)
on the Azure page. Run Command's output comes through Azure's authenticated
control plane, so its `fingerprint=` line is one Stage 4 can trust.

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

## What the script and the playbook check

Both stop with a reason rather than leave the account half-working or lock it
out. Before it changes anything, the onboarding script refuses:

- a run without root rights;
- a missing key, the unreplaced placeholder, or a line that is not a single
  OpenSSH public key of type `ssh-rsa`, `ssh-ed25519` or `ecdsa-sha2-nistp*`;
- a hash that is not a SHA-512 crypt hash, and a controller address that is
  not an IP address;
- a system other than Ubuntu 24.04 or AlmaLinux, Rocky Linux or RHEL 9.

It then installs any missing package, and still before it touches the
account it refuses:

- an SSH configuration whose `Match` rules depend on the client's address
  when no controller address is given;
- a key list in which no key can log in under the machine's SSH policy: a key
  type that `PubkeyAcceptedAlgorithms` leaves out, such as Ed25519 under a FIPS
  or STIG crypto policy, or an RSA key shorter than 2048 bits or than the
  server's `RequiredRSASize`.

While it makes its changes, it:

- refuses an existing `svc_ansible` with a system UID (below 1000);
- writes the key file as `svc_ansible` itself, so a link planted in its home
  cannot redirect root, and refuses an `authorized_keys` that is a directory;
- enforces, on every run, a home without group or world write permission,
  `.ssh` at mode 0700 and `authorized_keys` at 0600, both owned by the
  account, because SSH's `StrictModes` ignores keys in a writable place; and
  restores their SELinux labels where SELinux is enabled;
- refuses a sudoers file or SSH drop-in that is a link or not a regular file;
- checks the sudo rule with `visudo`, then the whole sudo configuration, and
  takes its rule back if that fails to parse;
- reads `sudo -l -U svc_ansible` and requires `(ALL : ALL) ALL` with no
  `NOPASSWD` or `!authenticate`, and no `rootpw`, `targetpw` or `runaspw`
  default, which would make sudo ask for another account's password;
- runs `sudo -k -n /usr/bin/true` as `svc_ansible`, which must fail: it
  catches a passwordless rule anywhere in the configuration;
- requires `/etc/ssh/sshd_config` to include `sshd_config.d/*.conf`, then
  checks `sshd -t` and the effective policy for `svc_ansible` arriving from the
  controller's address at each of the machine's addresses and SSH ports:
  public key only, no password or keyboard-interactive login, an
  `AuthorizedKeysFile` that includes `~/.ssh/authorized_keys`, and no
  `AllowUsers`, `AllowGroups`, `DenyUsers` or `DenyGroups` rule that keeps the
  account out (an entry it cannot judge, such as a pattern, is printed as a
  `warning:`);
- puts the previous drop-in back and leaves SSH alone when any SSH check
  fails, and also when SSH does not accept the reload.

The last line is `RESULT: OK` or `RESULT: FAILED: REASON`, also after an
unexpected error. The account, its keys and its password may already be
updated when a later check stops the run; running it again is safe.

The bootstrap playbook makes the same checks in its own way. It requires a
`--limit` that selects exactly one host, a supported system, single-line
public keys and a password of at least 12 characters, and at least one key
the machine's SSH policy accepts, all before it changes anything. It refuses a
link in place of `.ssh` or `authorized_keys`, writes the key file as
`svc_ansible`, and validates the sudoers rule with `visudo`. It reads the SSH
policy for the very connection the controller uses, checks the same settings
and the `Allow`/`Deny` rules, and on a failure puts the previous drop-in back
and does not reload SSH. After SSH is reloaded, it checks the sudo rights as
the script does, `sudo -k -n` included, and stops if they are wrong.

## Check

After the one command, the controller's last lines name the machine under
`Prepared and in the inventory:`, and the inventory lists it:

```bash
grep -n '^[^#]*ansible_host' /opt/ansible-lab/inventories/lab.ini
```

On the machine, the script's first run shows:

```text
password: set from PASSWORD_HASH
sudo: /etc/sudoers.d/90-ansible-lab written; svc_ansible's own password is required
RESULT: OK
```

Running it again is a good check. Without a password option, as
`sudo bash onboard-linux.sh --keys svc_ansible.pub --controller-address CONTROLLER_IP`
or the one command with `--keep-password`, it reports
`authorized keys unchanged`, `password: kept`, and `unchanged` for the sudo
rule and the SSH drop-in, then the same four lines. `kept` means it kept a
password set earlier; `NOT SET` means there is none yet. With a password again,
it reports `password: set from PASSWORD_HASH` again, because each hash of the
same password has a new random salt; that is fine too. After the bootstrap
playbook, its recap shows `failed=0`, and a repeat run `changed=0`. At the
machine's console, `sudo -l -U svc_ansible` lists `(ALL : ALL) ALL` without
`NOPASSWD`. Whether the controller can log in and use sudo is checked in
Stage 4, by Ping and Baseline preview.

## Save these values

| Value | Where it came from | Needed in |
| --- | --- | --- |
| The plain sudo password of `svc_ansible` | You chose it; saved in your password manager | Stage 4, Semaphore's Key Store; console recovery |
| The address you typed or pinned | Your choice, the same everywhere | Stage 4 and every later SSH run |
| The `name=`, `address=`, `group=` and `fingerprint=` lines (not after the one command) | The end of the script's output, or `inventory-info.sh` | Stage 4, pasted into `add-target.sh --from-info` |
| The whole `sudo bash controller/add-target.sh ...` command | The end of the bootstrap playbook's output | Stage 4, run as printed |

## When it fails

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| `Run it as your administrator account, without sudo: ...` | `onboard-target.sh` ran with `sudo` or as root | Run `bash controller/onboard-target.sh ...` as yourself; it asks for `sudo` where it needs it. |
| `Run it from a terminal to be asked for the sudo password, or pass --keep-password.` | `onboard-target.sh` has no terminal to ask on | Run it in an interactive SSH session, or pass `--keep-password` and set the password another way. |
| `The two entries differ; nothing was changed. Run it again.` or `The password has fewer than 12 characters; nothing was changed.` | A typing slip, or a short password | Run it again. |
| `Could not read /etc/semaphore/svc_ansible.pub. Was this controller made by the guide's installer?` | A controller set up by hand, or the `sudo` password was refused | On a controller set up by hand, use the SSH way with your own key, as [manual access](manual-access.md) shows. |
| `Could not log in to ADMIN@VM_ADDRESS.` | SSH's message above it names the cause: wrong name or address, `Permission denied`, a refused host key, `REMOTE HOST IDENTIFICATION HAS CHANGED` | Fix that and run it again for that machine. For a changed host key, see the row below. |
| `ADMIN@VM_ADDRESS is prepared, but add-target.sh did not add it ...` | `add-target.sh` refused, for example for a reserved hostname | Run it again for that machine alone with `--name NAME`, or as `add-target.sh`'s message says; see [Stage 4](stage-4-add-target-first-job.md#when-a-step-fails). |
| The last line is `RESULT: FAILED: ...` | The message names it: a key this SSH server refuses, a `NOPASSWD` rule, an SSH setting that overrides the account's, an unsupported system | Fix what it names and run the script again. It changed nothing that could lock you out: an SSH or sudo change that failed its check was taken back. The account, its keys and its password may already be updated; running it again is safe. |
| `RESULT: FAILED: run as root, for example with: sudo bash onboard-linux.sh` | The script ran without root rights | Run it with `sudo bash onboard-linux.sh ...`. |
| `RESULT: FAILED: replace REPLACE_WITH_AUTOMATION_PUBLIC_KEY with the controller's public key` | No key was given, so the script fell back to its unedited constant | Give the key with `--keys svc_ansible.pub`, and check with `ls` that the file is in the current folder. |
| `RESULT: FAILED: cannot read the key file ...` | The `--keys` file is not in the current folder | `ls`, then run it from the folder that holds the key. |
| `RESULT: FAILED: --ask-password needs openssl to hash the password; ...` | The machine has no `openssl` command | Install `openssl` on it, or make the hash on the controller and use `--password-hash-file`. |
| `RESULT: FAILED: PASSWORD_HASH must be a SHA-512 crypt hash ...` | A pasted hash was cut or changed on its way, for example by double quotes that expanded its `$` signs | Use `--ask-password` instead, or make the hash again. |
| `RESULT: FAILED: the SSH configuration has Match rules that depend on the client's address ...` | No controller address was given | Add `--controller-address CONTROLLER_IP` and rerun. The one command always gives it. |
| `RESULT: FAILED: none of the keys can log in to this SSH server ...` | A crypto policy, such as FIPS or a STIG, refuses the key type or its size | Use the RSA 4096 service key the installer made. |
| `password: NOT SET` | No password or hash was given to a new account | Run the one command again without `--keep-password`, or the script with `--ask-password`. |
| `scp` or `ssh` says `Permission denied (publickey)` for the administrator | The administrator accepts another machine's key only | [Manual access, step 3](manual-access.md#step-3-prepare-a-dedicated-target-account), or the console way. |
| `ssh` says `REMOTE HOST IDENTIFICATION HAS CHANGED`, or the playbook says `Host key verification failed` | The address answered with a different key than the pinned one, or no key is pinned for that exact address | Compare with the console value again. Remove an old entry only after you know why it changed: `ssh-keygen -R VM_ADDRESS`. A rebuilt machine also needs Stage 4's [rebuild steps](stage-4-add-target-first-job.md#do-rebuild-or-retire-a-target). |
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
The one command keeps that rule: it gives `add-target.sh` only the `name=`,
`group=` and `fingerprint=` values, read over the connection whose host key you
verified, and the address you typed yourself, never one the machine reports;
`add-target.sh` then scans the address and trusts only the key with that
fingerprint.

## Next

After the one command: [Stage 4: give Semaphore the sudo password](stage-4-add-target-first-job.md#do-give-semaphore-the-sudo-password).
After the other ways: [Stage 4: add the target and run the first job](stage-4-add-target-first-job.md).
