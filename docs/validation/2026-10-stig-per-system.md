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

Every step below ran live; the controllers ran this branch's commits `f1a97f8`
and `59eb6c6`, and every run's output was kept.

| Step | Result |
| --- | --- |
| Before the update | On the `v1.6.1` controller, Ping succeeded through Semaphore, and the old **STIG audit (vendor scan only)** scanned RHEL and AlmaLinux; Ubuntu stopped with the `usg` explanation until `usg` was installed. **Local SCAP content** was set to DISA's RHEL 9 benchmark in `content/`, as chapter 9 of that release showed, and its template scanned `lab-rhel`: 149 pass, 220 fail, 23 not applicable. |
| Plan | Eight per-system playbooks and `vars/stig_systems.yml` to add, three shared STIG files to update, twelve files current; four `content/` folders to create; two variable groups, four tabs and fourteen templates to add; the four old STIG templates and the **STIG** tab listed as replaced and kept; **Local SCAP content** listed as holding the operator's values. Nothing changed. |
| Apply | Added the Semaphore objects, committed the files with `.guide-files.json`, created `content/rhel/9`, `content/almalinux/9`, `content/rocky/9` and `content/ubuntu/24.04` with the folder's owner, group `semaphore` and mode 2750, and passed the readiness check. All fourteen new templates carried the vault password the seeded templates shared. |
| Per-system audits | **RHEL 9 · STIG audit** scanned `lab-rhel` and skipped `lab-alma`, naming **AlmaLinux 9 · STIG audit** for it; **AlmaLinux 9 · STIG audit** did the reverse; **Ubuntu 24.04 · STIG audit** scanned `lab-ubuntu`. Each fetched its reports under `stig-reports/<system>/<version>/`. The counts matched the old template's scan of the same hosts: RHEL 170 pass, 262 fail; AlmaLinux 155 pass, 268 fail. |
| No host of the system | **Rocky Linux 9 · STIG audit**, with only RHEL and AlmaLinux hosts in `enterprise_linux`, stopped on every host with an explanation naming the systems found. |
| Wrong system for an apply | **RHEL 9 · STIG apply (approval required)** with Limit `lab-alma` and the approval given was refused before any change, naming **AlmaLinux 9 · STIG apply**. |
| DISA SCAP file templates | With the benchmark still in `content/`, **RHEL 9 · STIG audit, DISA SCAP file** stopped before scanning and named the path it expected. After the file was moved to `content/rhel/9/` it scanned `lab-rhel` with the same counts as before the update, 149 pass, 220 fail, 23 not applicable, and skipped `lab-alma`. **Ubuntu 24.04 · STIG audit, DISA SCAP file** scanned `lab-ubuntu` from `content/ubuntu/24.04/`: 46 pass, 117 fail, 2 not applicable. |
| Apply through a per-system template | **AlmaLinux 9 · STIG apply, allow required reboot** on `lab-alma` applied the vendor remediation, rebooted, and took the target from 268 to 22 failing and 155 to 406 passing rules, as in the [earlier record](2026-09-onboard-stig.md). Ping then succeeded on all three targets. |
| Old templates after the update | The old **STIG audit (vendor scan only)** still scanned all three targets, with reports under `stig-reports/` without a system level. |
| `--remove-replaced` | A first run showed that `update-controller.sh` refused the option, which the Python updater accepted; the wrapper now passes it, and a test checks every option. The run then committed the files, saved all 26 templates and the **STIG** tab to a root-only file, deleted the four old templates and the tab, and kept **Local SCAP content** because it held the operator's values. Task history went from 14 to 11 tasks: the three runs of the deleted templates went with them. |
| An untouched replaced group | With **Local SCAP content** set back to its seeded placeholders, `seed-semaphore.py --update --remove-replaced` backed it up and deleted it. |
| After removal | The update reported nothing to do; Ping and **RHEL 9 · STIG audit** succeeded. |
| Fresh install | This branch's Enterprise Linux installer seeded the tabs **Lessons**, **Patching** and one **STIG ·** tab per system with 22 templates, created the per-system `content/` folders, passed readiness, and an update plan reported nothing to do. |

Offline tests, run in CI, cover what the live runs did not stage: a Rocky Linux
host, the Ubuntu apply, a replaced tab or variable group that a template of the operator's still
uses, a replaced template renamed after the plan, seeded templates with
different vault passwords, and a second removal run.

## Found and fixed

A review before the live run found eight problems, all fixed and then tested
above where they could be staged: removal ran before the lab folder held the
new playbooks; it would have deleted a **Local SCAP content** group holding the
operator's values without saving it; new templates lacked the vault password of
chapter 3b's per-target sudo option; an audit with no host of its system
succeeded while scanning nothing; one message kept a stray line break; the skip
and refusal messages named internal keys instead of templates; the seeder's own
`--remove-replaced` output listed planned rather than actual removals; and three
passages of the controller chapters described the old single STIG tab.

The live run found two more: the wrapper's refusal of `--remove-replaced`, and
the seeding summary printing tab names as `\u00b7` escapes.

The Azure example's `targets.yml` gave every target a 40 GB disk, which the
RHEL 9 pay-as-you-go image refuses because it is 64 GB itself, so the RHEL
target was created with `az vm create` and the same cloud-init file, as in the
earlier records. Release `v1.7.1` fixed this, and it was tested in a second
disposable group the same day: `controller.yml` made a RHEL 9 controller and
`targets.yml` a RHEL 9 target, each with a 64 GB disk, while the AlmaLinux
target kept 40 GB; a second run of both reported `changed=0`; the RHEL target's
cloud-init onboarding completed; and `remove.yml` deleted the group.
