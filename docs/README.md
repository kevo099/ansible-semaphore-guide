# The guide's pages

[Back to the guide](../README.md)

## The workflow, in order

| Stage | Page |
| --- | --- |
| 0 | [Plan the lab and create the controller VM](stage-0-plan.md) |
| 1 | [Install the controller](stage-1-controller.md) |
| 2 | [Onboard a machine that already exists](stage-2-existing-machines.md) |
| 3 | [Pre-deploy new VMs with cloud-init](stage-3-new-vms-cloud-init.md) |
| 4 | [Add the target and run the first job](stage-4-add-target-first-job.md) |

Stages 2 and 3 are alternatives, chosen per machine.
[The whole path as one flowchart](ONBOARDING.md) shows every branch.

## Runbooks

[Runbooks: common tasks](runbooks.md): onboard one or several machines,
pre-deploy a batch of VMs from a Proxmox template, give or change the sudo
password, check every machine's health, reboot one target, retire a target,
recover from a rebuilt target or controller, update the controller, read a
target's values again, and unlock `svc_ansible` after hardening.

## Worked platforms

- [Proxmox VE](platform-proxmox.md): build VMs from an ISO or a cloud image,
  snippets, the console, and the path end to end.
- [Azure](platform-azure.md): create, onboard and remove a lab with the
  playbooks in `platforms/azure/`, and Run Command for VMs without SSH.

## Go further

| Chapter | Subject |
| --- | --- |
| [5](05-cli-lessons.md) | Run, inspect and change the playbooks from the terminal |
| [6](06-semaphore.md) | Semaphore's project, keys, inventory and templates |
| [7](07-git-and-vscode.md) | Git and VS Code |
| [8](08-operations.md) | Patching and daily operations |
| [9](09-security-benchmarks.md) | Optional CIS and STIG practice |
| [10](10-recovery.md) | Backup, restore and rebuild |
| [11](11-troubleshooting.md) | Troubleshooting |
| [12](12-learning-path.md) | Learning exercises and RHCE alignment |
| [14](14-inputs-and-templates.md) | Inputs and templates |
| [15](15-identity.md) | Identity, roles and credentials |
| [16](16-semaphore-operations.md) | Schedules, notifications and task control |
| [17](17-api-and-integrations.md) | API and integrations |
| [18](18-runners.md) | Runners |

The chapter numbers are the ones earlier releases used; chapters 1 to 4 and 13
became the stage, by-hand and platform pages.

## By hand, and upkeep

- [Build the Ubuntu controller by hand](manual-controller-ubuntu.md): what the
  installer does, one step at a time.
- [SSH, sudo and the automation account by hand](manual-access.md): what the
  onboarding files do, one step at a time.
- [Update a controller to a newer guide release](controller-update.md).
- [Settings and your own playbooks](settings.md): the values meant to be changed, and where your playbooks go.

## Reference

- [Community coverage](COMMUNITY-COVERAGE.md): each Semaphore capability, its
  edition and its test result.
- Appendices: [browser access](appendices/browser-access.md),
  [Git migration](appendices/git-migration.md),
  [identity providers](appendices/identity-providers.md),
  [maintenance](appendices/maintenance.md),
  [other task apps](appendices/other-apps.md),
  [security baselines](appendices/security-baselines.md) and
  [task identity](appendices/task-identity.md).
- [Validation and limitations](VALIDATION.md), with the dated records in
  [`validation/`](validation/).
- [Official references](REFERENCES.md).
