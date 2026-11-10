# Onboarding files

These files prepare a Linux machine, Ubuntu 24.04 or AlmaLinux, Rocky Linux or
RHEL 9, for the guide's automation account, `svc_ansible`: the controller's
service key as its only login, sudo with its own password, and an SSH drop-in
that requires a key for it. The folders follow the guide's stages:
`existing/` is [Stage 2](../docs/stage-2-existing-machines.md), for a machine
that already runs; `new-vm/` is [Stage 3](../docs/stage-3-new-vms-cloud-init.md),
for a VM you are about to create. Both stages hand off to
[Stage 4](../docs/stage-4-add-target-first-job.md), which adds the machine on the
controller. [By hand](../docs/manual-access.md) shows the same steps without
these files.

For a machine that already exists, you usually run none of these files
yourself: on the controller, `bash controller/onboard-target.sh ADMIN@ADDRESS`
([the script](../controller/onboard-target.sh)) copies `existing/onboard-linux.sh` and the service key to the machine over SSH,
runs it there with `sudo`, and adds the machine to the lab inventory, as
[Stage 2](../docs/stage-2-existing-machines.md#do-onboard-it-in-one-command-from-the-controller)
shows. The table lists the files for the other ways.

| File | Stage | Use it when | Where it runs |
| --- | --- | --- | --- |
| [`existing/onboard-linux.sh`](existing/onboard-linux.sh) | 2 | The machine exists and you can get a root shell on it: over SSH, at its console, or through Azure Run Command; `controller/onboard-target.sh` runs it for you over SSH | On the machine, as root |
| [`existing/bootstrap-existing-vm.yml`](existing/bootstrap-existing-vm.yml) | 2 | The machine exists, the controller can log in as its administrator with a key, and its host key is pinned | On the controller, in the guide's folder, one machine per run |
| [`new-vm/cloud-init.yaml`](new-vm/cloud-init.yaml) | 3 | You are creating the VM and can give it cloud-init data: vendor data on Proxmox or in a NoCloud seed, custom data on Azure | On the VM, at first boot |
| [`new-vm/fill-cloud-init.sh`](new-vm/fill-cloud-init.sh) | 3 | You fill `cloud-init.yaml` with the service key, and optionally the sudo password's hash | On the controller, in the guide's folder |
| [`inventory-info.sh`](inventory-info.sh) | 2 or 3 | The machine is prepared and you need its values for the controller again, for example after cloud-init | On the machine, `sudo sh inventory-info.sh`; read-only |

## Inputs

Each file needs the controller's service key, which
`sudo cat /etc/semaphore/svc_ansible.pub` prints on a controller made by the
installer, and which the installer also leaves as `~/svc_ansible.pub`. The
sudo password never travels in clear: `onboard-linux.sh` asks for it and
hashes it on the machine (`--ask-password`) or takes a SHA-512 hash from
`openssl passwd -6`, the bootstrap playbook asks for the password, and
cloud-init sets none by default, because user data is no place for secrets.
As an opt-in, `fill-cloud-init.sh --with-password` adds the password's hash to
your filled copy, which must then stay private, as
[Stage 3](../docs/stage-3-new-vms-cloud-init.md#optional-let-the-file-set-the-sudo-password)
explains.

`onboard-linux.sh` takes its three inputs from options on its command line,
from environment variables, or from the constants at its top; options win over
variables, and variables over constants:

| Option | Environment variable | Constant | Holds |
| --- | --- | --- | --- |
| `--keys FILE` | `ONBOARD_PUBLIC_KEYS` | `PUBLIC_KEYS` | Every public key that may log in as `svc_ansible`, one per line; it replaces the account's authorized keys |
| `--ask-password`, or `--password-hash-file FILE` | `ONBOARD_PASSWORD_HASH` | `PASSWORD_HASH` | Optional: the sudo password, asked twice and hashed on the machine, or its hash from `openssl passwd -6`; a hash file is removed when the script ends |
| `--controller-address IP` | `ONBOARD_CONTROLLER_ADDRESS` | `CONTROLLER_ADDRESS` | Optional: the controller's IP address as the machine sees it |

With the options, the file needs no editing. On the machine, in the folder
that holds the script and the key:

```bash
sudo bash onboard-linux.sh --keys svc_ansible.pub --ask-password --controller-address CONTROLLER_IP
```

[Stage 2](../docs/stage-2-existing-machines.md#do-run-the-onboarding-script-over-ssh)
shows how the file and the key get there; Azure Run Command passes the
environment variables. `inventory-info.sh` has constants only:
`CONTROLLER_ADDRESS`, `TARGET_ADDRESS` and `INVENTORY_NAME`, all optional.
`cloud-init.yaml` has one placeholder, `REPLACE_WITH_AUTOMATION_PUBLIC_KEY`,
which `fill-cloud-init.sh` fills in Stage 3.

## What they print: data, not a command

The files that run on the machine end by printing its values, as data and not
as a command:

```text
Add this VM on the controller: in the guide's folder, run
  sudo bash controller/add-target.sh --from-info
then paste these lines and press Ctrl-D:
name=NAME
address=ADDRESS
group=GROUP
fingerprint=SHA256:...
```

After the one command, `onboard-target.sh` has already given these values to
`add-target.sh`. Otherwise, on the controller, run
`sudo bash controller/add-target.sh --from-info`, typed or
copied from the guide rather than from the machine's output, and after its
prompt paste the four lines, or the whole output.
[`controller/add-target.sh`](../controller/add-target.sh) takes only those values
and checks them, scans the machine, keeps only the host key that matches the
fingerprint, and adds the machine to the lab inventory; it ignores every other
line and runs none of it. cloud-init's copy starts each line with `onboard:`,
and a console or the journal adds a stamp before that; it accepts both. `onboard-linux.sh` and `cloud-init.yaml` leave out a value the
machine cannot read, and a hostname the inventory reserves, such as `localhost`
or `ubuntu`. `add-target.sh` then says which value is missing and the option
that gives it, `--name`, `--address` or `--fingerprint`; add only that option,
with a value you read yourself at the machine's console.
`onboard-linux.sh` prints `RESULT: OK` as its last line, after the values.
`inventory-info.sh` leaves nothing out: it stops with `INFO FAILED` and names
the setting to fill in at its top. Add `--lab-dir DIR` for a lab folder other
than `/opt/ansible-lab`.

The bootstrap playbook runs on the controller and prints the whole
`add-target.sh` command instead, built there from the controller's inventory
and the fingerprint it read; run that command, replacing `NAME`, `ADDRESS` or
`FINGERPRINT` if shown. [Stage 4](../docs/stage-4-add-target-first-job.md#why-the-vm-prints-lines-not-a-command)
explains why the two differ.
