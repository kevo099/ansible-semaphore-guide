# Validation record: from a VM to an onboarded target, October 2026

[Back to validation and limits](../VALIDATION.md) · [From a VM to an onboarded target](../ONBOARDING.md)

On 19 October 2026, every onboarding path of the guide was run on Azure, first
as release `v1.7.1` published it and then with this release's fixes, in a
disposable resource group that was then deleted. A review of the scripts,
playbooks and documentation ran beside it, and each of its findings was checked
by a second reviewer before it was fixed.

## How it ran

- **Subscription:** a new pay-as-you-go subscription, `eastus2`, with 10 vCPUs
  per region. It had no quota for the guide's `Standard_D2als_v6`, so every VM
  used `Standard_D2als_v7`, 2 vCPUs and NVMe disks.
- **Controller:** AlmaLinux 9.8, created by `controller.yml`, its host key
  pinned by comparing the Run Command fingerprint with `ssh-keyscan`, and
  installed with `install-controller-el9.sh --apply --expose https` from tag
  `v1.7.1`, as an existing controller would have been.
- **Targets, one onboarding path each:**

| Target | Created by | Prepared by |
| --- | --- | --- |
| AlmaLinux 9.8 | `targets.yml` | `cloud-init.yaml`, then `bootstrap-existing-vm.yml` for the password |
| Rocky Linux 9.8 | `targets.yml`, with the Marketplace plan | `cloud-init.yaml`, then a managed Run Command with the unedited `onboard-linux.sh` and the hash as a protected parameter |
| RHEL 9.8 pay-as-you-go | `az vm create`, no custom data | `onboard-linux.sh` through `az vm run-command invoke`, key, hash and controller address pasted in |
| Ubuntu 24.04 Ubuntu Pro | `az vm create`, no custom data | `bootstrap-existing-vm.yml` from the controller, the whole job |

## Results on v1.7.1

| Step | Result |
| --- | --- |
| Network and controller | `network.yml` and `controller.yml` worked with the CLI login selected through `AZURE_CONFIG_DIR`. The installer finished in 35 seconds and passed readiness, with 22 templates. With `--expose https` it printed the NIC's private address, which a workstation cannot use. |
| Rocky Linux with `targets.yml` | Refused with `VMMarketplaceInvalidInput`: the image needs its Marketplace plan, which the playbook could not pass. The failed create left a VM in the `Failed` state that later runs could not update until it was deleted. The foundation's Community Gallery image declares no NVMe support and did not start on `Standard_D2als_v7`. With a `plan` passed through and the image's terms accepted once, the VM was created. |
| An image given by ID | `v1.7.1`'s disk-size rule failed on an image without a `publisher`, such as a gallery image: `object of type 'dict' has no attribute 'publisher'`. |
| cloud-init | AlmaLinux and Rocky Linux both reported `onboard: svc_ansible is ready; set its sudo password next`. |
| Run Command, script pasted | RHEL: `RESULT: OK` in 32 seconds, account created, password set from the hash, SSH policy checked from the controller's address. |
| Run Command, managed, protected hash | Rocky Linux: `RESULT: OK` in 34 seconds; the work cloud-init had done was reported as unchanged, and reading the command back showed no hash. |
| `bootstrap-existing-vm.yml` | **Failed on both hosts** at `Check that the policy is the one chapter 4 expects`, after setting the password, so the SSH drop-in was not applied. ansible-core 2.21 passed the expression's `regex_replace` backreference literally, so the default relative `AuthorizedKeysFile` became `/home/svc_ansible/\1ssh/authorized_keys`. The run stopped safely and restored the previous drop-in. With the fix it completed on both, and a repeat reported no changes. |
| `add-target.sh` | Added AlmaLinux and Ubuntu with the fingerprints read through Run Command. |
| `inventory-info.sh` | Its first live run. Through Run Command it printed 3.6 KB for RHEL and Rocky Linux, below the 4 KB limit; the generated block, pasted on the controller, added both, and a repeat printed `Already present`. |
| Semaphore | With one shared sudo credential, Ping and Baseline preview succeeded on all four. Baseline, Users and Webserver changed things and then repeated with `changed=0`; Patch preview and Patch without reboot ran, leaving the kernel reboot on Enterprise Linux to the operator. |
| Per-system STIG audits | Each scanned only its own system and skipped the others. Vendor content: RHEL 170 pass and 262 fail, AlmaLinux 155 and 268, Rocky Linux 159 and 264, Ubuntu 54 and 67; DISA files: RHEL 149 and 220, Ubuntu 46 and 117. No scanner errors; the RHEL, AlmaLinux and Ubuntu counts equal the earlier records. |
| STIG apply with reboot, all four | Each took a few minutes, rebooted and passed: failing rules RHEL 262 → 15, AlmaLinux 268 → 22, Rocky Linux 264 → 27, Ubuntu 67 → 8. Ping, Baseline preview, Users, Webserver and Patch preview then succeeded with `changed=0`. |
| After the STIG | Enterprise Linux: 60-day password age, `faillock` with `deny = 3` and `unlock_time = 0`, the `FIPS:STIG` crypto policy without FIPS mode, and only ECDSA and RSA host keys offered. An administrator's RSA key logged in without sudo; an Ed25519 key was refused. No `AllowUsers` or `AllowGroups` rule was added. |
| An expired password | After `chage -d 0 svc_ansible` on hardened Rocky Linux, Ping failed with `Password change required but no TTY available`. `onboard-linux.sh` through Run Command with a new hash restored the account and the 60 days, and Ping and Baseline preview succeeded again. |

## The fixes, checked live

The controller was then updated from `v1.7.1` to this release with
`update-controller.sh`:

| Fix | Result |
| --- | --- |
| Templates that schedules run | Two old-style STIG templates were created through the API, one with a nightly schedule. The plan listed the scheduled one as kept, naming the schedule, and `--remove-replaced` removed only the other, after backing up templates, schedules and integrations. With the schedule deleted, a second run removed it too. |
| Readiness | The check reported 16 checks, including the new `port_3000_listening` and `port_5432_listening`, and passed before and after. |
| Exposure rerun | `expose-semaphore.sh --mode https` on the exposed controller kept Semaphore running and the certificate's fingerprint unchanged. |
| SSH connection reuse | After the one-line `config.json` edit that chapter 3 gives for existing controllers, control sockets appeared under `/var/lib/semaphore/.ansible/cp`, and Baseline preview against the four hardened targets took 14.5 seconds instead of 19. |
| No sudo before the scope check | During **RHEL 9 · STIG audit**, the skipped AlmaLinux and Rocky Linux hosts logged no sudo by `svc_ansible`; during AlmaLinux's own audit, its host logged twelve. |
| Report folders and totals | Each audit wrote one folder per run, such as `rhel/9/20261019T060931Z`, and its summary added `selected_result_instances`: 477 on Enterprise Linux and 230 on Ubuntu. |

RESULTS_PENDING
