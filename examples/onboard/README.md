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
| [`inventory-info.sh`](inventory-info.sh) | The VM is prepared and you want its controller command through Azure Run Command, for example after cloud-init | On the VM, read-only |

Each of them ends by printing one line to run on the controller, in the
guide's folder:

```text
sudo bash scripts/add-target.sh --name NAME --address ADDRESS --group GROUP --fingerprint SHA256:...
```

[`scripts/add-target.sh`](../../scripts/add-target.sh) scans the VM, keeps
only the host key that matches the fingerprint, and adds the VM to the lab
inventory. Check that the line you paste is that single command and nothing
else, then run it.

Insert the controller's public key where each file says so. On a controller
made by either installer, that is the output of
`sudo cat /etc/semaphore/svc_ansible.pub`. The sudo password never travels in
clear: `onboard-linux.sh` takes a SHA-512 hash from `openssl passwd -6`, the
bootstrap playbook asks for it, and cloud-init sets none, because custom data
is no place for secrets.
