# Onboarding files

These files prepare a Linux VM for the guide's automation account,
`svc_ansible`: the controller's public key, password-protected sudo and the
SSH settings of [chapter 4](../../docs/04-access.md). Start with
[the onboarding page](../../docs/ONBOARDING.md), whose flowchart shows which
one fits your VM.

| File | Use it when | Where it runs |
| --- | --- | --- |
| [`cloud-init.yaml`](cloud-init.yaml) | You are creating the VM and can give it custom data | At first boot, through cloud-init |
| [`onboard-linux.sh`](onboard-linux.sh) | The VM exists and you can run a script as root: Azure Run Command, `sudo bash` over SSH, or the console | On the VM, as root |
| [`../bootstrap-existing-vm.yml`](../bootstrap-existing-vm.yml) | The VM exists and the controller can log in as its administrator, whose sudo works | On the controller, one host per run |
| [`inventory-info.sh`](inventory-info.sh) | The VM is prepared and you want its values for the controller through Azure Run Command, for example after cloud-init | On the VM, read-only |

The files that run on the VM end by printing its values, as data and not as a
command:

```text
Add this VM on the controller: in the guide's folder, run
  sudo bash scripts/add-target.sh --from-info
then paste these lines and press Ctrl-D:
name=NAME
address=ADDRESS
group=GROUP
fingerprint=SHA256:...
```

On the controller, run `sudo bash scripts/add-target.sh --from-info`, typed or
copied from this page rather than from the VM's output, and after its prompt
paste the four lines, or the whole output.
[`scripts/add-target.sh`](../../scripts/add-target.sh) takes only those values
and checks them, scans the VM, keeps only the host key that matches the
fingerprint, and adds the VM to the lab inventory; it ignores every other line
and runs none of it. cloud-init's copy starts each line with `onboard:`, which
it accepts. `onboard-linux.sh` and `cloud-init.yaml` leave out a value the VM
cannot read, and a hostname the inventory reserves, such as `localhost` or
`ubuntu`. `add-target.sh` then says which value is missing and the option that
gives it, `--name`, `--address` or `--fingerprint`; add only that option, with
a value you read yourself through Run Command or the console.
`onboard-linux.sh` prints `RESULT: OK` as its last line, after the values.
`inventory-info.sh` leaves nothing out: it stops with `INFO FAILED` and names
the setting to fill in at its top, `CONTROLLER_ADDRESS`, `TARGET_ADDRESS` or
`INVENTORY_NAME`. Add `--lab-dir DIR` for a lab folder other than
`/opt/ansible-lab`. The bootstrap playbook runs on the
controller and prints the whole `add-target.sh` command instead; run that
command, replacing `NAME`, `ADDRESS` or `FINGERPRINT` if shown and adding
`--lab-dir DIR` for another lab folder, as its message says.
[The onboarding page](../../docs/ONBOARDING.md#why-the-vm-prints-lines-not-a-command)
explains why.

Insert the controller's public key where each file says so. On a controller
made by either installer, that is the output of
`sudo cat /etc/semaphore/svc_ansible.pub`. The sudo password never travels in
clear: `onboard-linux.sh` takes a SHA-512 hash from `openssl passwd -6`, the
bootstrap playbook asks for it, and cloud-init sets none, because custom data
is no place for secrets.
