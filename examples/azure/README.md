# Azure example playbooks

Create, stop and remove a small Azure lab: a network, an optional controller
with the only public address, and target VMs that
[`../onboard/cloud-init.yaml`](../onboard/cloud-init.yaml) prepares at first
boot. [Chapter 13](../../docs/13-azure.md) explains each step, and
[the onboarding page](../../docs/ONBOARDING.md) shows where they fit between
a new VM and a target Semaphore can run.

## Before the first run

- The Azure CLI, signed in to the subscription you mean (`az account show`),
  and the separate Python environment with the Azure collection that
  chapter 13 sets up.
- `vars.yml`, a copy of [`vars.example.yml`](vars.example.yml) with every
  `REPLACE_` value filled in. Git ignores it.
- Two public keys: your administrator's RSA key, and in `files/` a copy of
  the key Semaphore logs in with, which on a controller made by either
  installer is `/etc/semaphore/svc_ansible.pub`.
- Quota for every VM you create at the same time, in a size your
  subscription allows: `az vm list-usage --location REGION`.
- For Rocky Linux targets, the Marketplace terms of its image, accepted once
  per subscription:
  `az vm image terms accept --urn resf:rockylinux-x86_64:9-base:latest`.

## Run order

Run each playbook from this folder with
`~/azure-venv/bin/ansible-playbook -i localhost, PLAYBOOK`.

| Step | Playbook | Result |
| --- | --- | --- |
| 1 | [`network.yml`](network.yml) | Resource group, targets' security group, VNet and subnet |
| 2 | [`controller.yml`](controller.yml) | Optional controller with a static public address; SSH from your prefix only |
| 3 | Install the controller | [Chapter 3](../../docs/03-controller.md) or [3b](../../docs/03-controller-el9.md); then copy its service key into `files/` |
| 4 | [`targets.yml`](targets.yml) | Target VMs with private addresses, prepared by cloud-init |
| 5 | Onboard each target | [The onboarding page](../../docs/ONBOARDING.md): sudo password, then `add-target.sh` on the controller |
| 6 | [`power.yml`](power.yml) | `-e azure_power=deallocated` stops compute billing; `running` starts it again |
| 7 | [`remove.yml`](remove.yml) | `-e remove_confirm=RESOURCE_GROUP` removes what the lab created |

[`tasks-preflight.yml`](tasks-preflight.yml) is the shared check every
playbook runs first; [`requirements.yml`](requirements.yml) pins the Azure
collection.
