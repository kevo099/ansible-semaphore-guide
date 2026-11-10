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

| File | Stage | Use it when | Where it runs |
| --- | --- | --- | --- |
| [`existing/onboard-linux.sh`](existing/onboard-linux.sh) | 2 | The machine exists and you can get a root shell on it: over SSH, at its console, or through Azure Run Command | On the machine, as root |
| [`existing/bootstrap-existing-vm.yml`](existing/bootstrap-existing-vm.yml) | 2 | The machine exists, the controller can log in as its administrator with a key, and its host key is pinned | On the controller, in the guide's folder, one machine per run |
| [`new-vm/cloud-init.yaml`](new-vm/cloud-init.yaml) | 3 | You are creating the VM and can give it cloud-init data: vendor data on Proxmox or in a NoCloud seed, custom data on Azure | On the VM, at first boot |
| [`inventory-info.sh`](inventory-info.sh) | 2 or 3 | The machine is prepared and you need its values for the controller again, for example after cloud-init | On the machine, `sudo sh inventory-info.sh`; read-only |

## Inputs

Each file needs the controller's service key, which
`sudo cat /etc/semaphore/svc_ansible.pub` prints on a controller made by the
installer, and which Stage 1 saves as `~/svc_ansible.pub`. The sudo password
never travels in clear: `onboard-linux.sh` takes a SHA-512 hash from
`openssl passwd -6`, the bootstrap playbook asks for the password, and
cloud-init sets none, because user data is no place for secrets.

`onboard-linux.sh` takes its three inputs either from the constants at its top
or from environment variables, which win when they are set:

| Constant | Environment variable | Holds |
| --- | --- | --- |
| `PUBLIC_KEYS` | `ONBOARD_PUBLIC_KEYS` | Every public key that may log in as `svc_ansible`, one per line; it replaces the account's authorized keys |
| `PASSWORD_HASH` | `ONBOARD_PASSWORD_HASH` | Optional: the sudo password's hash from `openssl passwd -6` |
| `CONTROLLER_ADDRESS` | `ONBOARD_CONTROLLER_ADDRESS` | Optional: the controller's IP address as the machine sees it |

With the variables, the file needs no editing. In a root shell on the machine:

```bash
ONBOARD_PASSWORD_HASH=$(openssl passwd -6) && export ONBOARD_PASSWORD_HASH
export ONBOARD_PUBLIC_KEYS="$(cat svc_ansible.pub)"
export ONBOARD_CONTROLLER_ADDRESS=CONTROLLER_IP
bash onboard-linux.sh
```

[Stage 2](../docs/stage-2-existing-machines.md#do-run-the-onboarding-script-over-ssh)
shows how the file and the key get there, and why this form keeps the hash out
of the process list. `inventory-info.sh` has constants only:
`CONTROLLER_ADDRESS`, `TARGET_ADDRESS` and `INVENTORY_NAME`, all optional.
`cloud-init.yaml` has one placeholder, `REPLACE_WITH_AUTOMATION_PUBLIC_KEY`,
which Stage 3 fills.

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

On the controller, run `sudo bash controller/add-target.sh --from-info`, typed or
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
