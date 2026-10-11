# Validation record: STIG lessons per system, October 2026

[Back to validation and limits](../VALIDATION.md) · [The seeded STIG templates](../09-security-benchmarks.md#the-seeded-stig-templates) · [Update a controller](../03-controller.md#update-a-controller-to-a-newer-guide-release)

On 11 October 2026, the per-system STIG playbooks, tabs and templates, and the
update from release `v1.6.1`, were tested on Azure in a disposable resource
group, which was then deleted.

## How it ran

- **Subscription and VMs:** the sponsored subscription of the
  [earlier Azure records](2026-09-azure.md), `eastus2`, `Standard_D2als_v6`.
- **Controllers:**
  - AlmaLinux 9.8, installed with the Enterprise Linux installer from tag
    `v1.6.1`, which seeds twelve templates on the tabs Lessons, Patching and
    STIG, then updated to this branch;
  - AlmaLinux 9.8, installed fresh from this branch.
- **Targets:** RHEL 9.8 pay-as-you-go, AlmaLinux 9.8 and Ubuntu 24.04 with
  Ubuntu Pro, prepared at first boot by `examples/onboard/cloud-init.yaml`,
  given a sudo password, and added with `add-target.sh`: `lab-rhel` and
  `lab-alma` in `enterprise_linux`, `lab-ubuntu` in `ubuntu`. Every template
  carried a vault password, as chapter 3b's per-target sudo option sets up.
- **DISA content:** RHEL 9 V2R9 and Ubuntu 24.04 V1R5 SCAP benchmarks, with
  the SHA-256 checksums recorded in the
  [onboarding and STIG record](2026-09-onboard-stig.md).

## Results

RESULTS_TABLE

Offline tests, run in CI, cover what the live runs did not stage: a Rocky Linux
host, a replaced tab or variable group that a template of the operator's still
uses, a replaced template renamed after the plan, seeded templates with
different vault passwords, and a second removal run.
