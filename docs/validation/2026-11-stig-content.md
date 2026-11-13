# Validation record: STIG content against DISA's October releases, November 2026

[Back to validation and limits](../VALIDATION.md) · [Chapter 9](../09-security-benchmarks.md)

On 13 November 2026 the STIG profiles that the vendors package were compared
with the releases DISA dated 30 September 2026. The STIG playbooks then gained
three things: a line that names the release a scan measured, a findings file
that lists the open rules by DISA category and STIG ID, and an exceptions
(XCCDF tailoring) file. The seeded DISA variable groups now name a folder
instead of one release's file, and **STIG apply** no longer restarts the
controller it runs from. The changes were then run on a registered RHEL 9.8
controller that was also its own target, and on an Ubuntu 24.04 target with
Ubuntu Pro. This record says what was compared, what ran, what the run changed
and what remains unverified.

## How the content was compared

- **DISA's files,** downloaded without an account from `dl.dod.cyber.mil`:
  the manual STIGs RHEL 9 V2R9 and V2R10, Ubuntu 24.04 V1R7 and AlmaLinux OS 9
  V1R8, and the SCAP benchmarks RHEL 9 V2R10 and Ubuntu 24.04 V1R6. The V2R10
  and V1R6 SCAP files were last modified on 5 October; on 28 September they
  were not there yet.

  | SCAP benchmark | SHA-256 of the ZIP |
  | --- | --- |
  | `U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.zip` | `951217ebb09ef6f58521da5608fb3b2794e9fb56196c6308319322cc3b85497c` |
  | `U_CAN_Ubuntu_24-04_LTS_V1R6_STIG_SCAP_1-3_Benchmark.zip` | `f3730f42e264143503cbe3b835b598fa7416e9d279fa85b2bb6740b6b78f7e6c` |

- **The vendors' content:** `scap-security-guide-0.1.82-2.el9_8`. Red Hat's
  own package, built on 8 September 2026, was read on the registered RHEL 9.8
  machine of the live run. AlmaLinux's and Rocky Linux's packages of the same
  version, the newest in their public repositories that day, were unpacked
  without installing them. Rocky Linux's package also carries
  `ssg-rhel9-ds.xml`; it gives the same figures as Red Hat's file.
- **By STIG ID.** DISA names a rule's STIG ID in the rule's `version`; the
  vendors' content names it in a rule's `reference`. A DISA rule counts as
  covered when a rule the `stig` profile selects names its ID.
- **Ubuntu's content** comes through Ubuntu Pro. On 13 November, after
  `apt-get update`, the newest Ubuntu Security Guide was 24.04.8 and `usg list`
  showed one STIG profile, `stig-v1r1`, benchmark version V1R1.

## What the comparison found

| Compared | Result |
| --- | --- |
| DISA RHEL 9 V2R9 to V2R10 | 445 rules in both. Added: `RHEL-09-271011`, `RHEL-09-654176` and `RHEL-09-672055`, the last one CAT I. Removed: `RHEL-09-171011`, `RHEL-09-215030` and `RHEL-09-215065`. 205 further rules carry a new revision. CAT I rules went from 28 to 29. |
| RHEL 9 `stig` profile, Red Hat's 0.1.82 | States V2R9. Selects 481 rules, which name 441 STIG IDs. 439 of V2R10's 445 IDs are covered. Not covered: the three V2R10 added, and `RHEL-09-211035`, `RHEL-09-214030` and `RHEL-09-654270`. Named by the profile and absent from V2R10: `RHEL-09-171011` and `RHEL-09-672030`. Of the 439, ten have no automated check and 37 no shell fix. |
| AlmaLinux 9 `stig` profile, 0.1.82 | Titled "DISA STIG for AlmaLinux OS 9" and states V2R9. The same 481 rules; every STIG ID it names begins with `RHEL-09`, none with `ALMA-09`. It covers none of the 439 IDs of DISA's AlmaLinux OS 9 V1R8 and the same 439 of RHEL 9 V2R10. |
| Rocky Linux 9 `stig` profile, 0.1.82 | Titled "DISA STIG for Red Hat Enterprise Linux 9" and states V2R9. The same 481 rules, and no STIG ID on any of them. |
| Ubuntu 24.04, Ubuntu Security Guide 24.04.8 | Supplies the STIG as V1R1. DISA's manual STIG is V1R7 and its SCAP benchmark V1R6. The content was not compared rule by rule. |
| DISA's SCAP benchmarks | RHEL 9 V2R10 automates 393 of the manual's 445 rules; Ubuntu 24.04 V1R6 automates 168, and the manual V1R7 has 195. Each lists the same eleven profile IDs as the release before it. |

## The live run

**Where:** two virtual machines on Proxmox VE, each returned to its snapshot
afterwards.

| Machine | Software |
| --- | --- |
| `rhel9-vendor01`, RHEL 9.8, registered. The controller, installed from this branch with `controller/install-controller-el9.sh`, and its own target. | ansible-core 2.21.4, Semaphore 2.19.12, `scap-security-guide-0.1.82-2.el9_8`, `openscap-scanner` and `openscap-utils` 1.3.14 |
| `ubuntu24-vendor01`, Ubuntu 24.04.5 with Ubuntu Pro. A target. | `usg` and `usg-benchmarks` 24.04.8, `openscap-scanner` 1.3.9 |

Both machines were added with `controller/onboard-target.sh`, and every scan
and fix below ran as a seeded template through Semaphore's API, which sends
what the Run dialog sends. The commands of chapter 9 were typed as the chapter
gives them.

### Release line, categories and findings file

| Template | Release line | Failing rules: CAT I, II, III, without a category | Findings file |
| --- | --- | --- | --- |
| **RHEL 9 · STIG audit** | `STIG release V2R9: profile 'DISA STIG for Red Hat Enterprise Linux 9' ... 0.1.82, ... scanner cpe:/a:redhat:openscap:1.3.14; no exceptions file` | 10, 238, 15, 4 | 277 rules: 267 failing, ten not checked |
| **Ubuntu 24.04 · STIG audit** | `STIG release V1R1: profile 'Canonical Ubuntu 24.04 LTS Security Technical Implementation Guide (STIG) V1R1' ... 0.1.78, ... scanner cpe:/a:redhat:openscap:1.3.9; no exceptions file` | 4, 54, 6, 0 | 68 rules: 64 failing, four not checked |

The category line named the failing CAT I rules by STIG ID, for example
`RHEL-09-211045, RHEL-09-211050, RHEL-09-212010`, and the path of
`audit-findings.csv` beside `audit.xml`.

### DISA's benchmarks from the content folders

The two ZIP files were downloaded on the controller into `content/rhel/9/` and
`content/ubuntu/24.04/` with the commands of chapter 9; their checksums are
the ones above. The seeded variable groups, which name the folders, were not
edited.

| Template and state of the target | Release line | Pass | Fail | Not applicable | Unknown | Task duration |
| --- | --- | --- | --- | --- | --- | --- |
| **RHEL 9 · STIG audit, DISA SCAP file**, before any fix | `STIG release V2R10 (Benchmark Date: 30 Sep 2026) ... copied from U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml` | 150 | 220 | 22 | 1 | 18 s |
| The same, after the vendor's fixes and a reboot | the same | 345 | 22 | 25 | 1 | 20 s |
| **Ubuntu 24.04 · STIG audit, DISA SCAP file**, before any fix | `STIG release V1R6 (Benchmark Date: 30 Sep 2026) ... copied from U_CAN_Ubuntu_24-04_LTS_V1R6_STIG_SCAP_1-3_Benchmark.xml` | 46 | 120 | 2 | 0 | 8 min 40 s |
| The same, after the vendor's fixes and a reboot | the same | 142 | 24 | 2 | 0 | 8 min 54 s |

- The scans after the fixes ran on the machines of
  [the fixes below](#fixes-with-an-exceptions-file), where the rules of the
  exceptions files had been left as they were: four on RHEL, two on Ubuntu.
- With a second file whose name ends in `_Benchmark.xml` in `content/rhel/9/`,
  the run stopped before scanning and named both files.
- The unknown result on RHEL is DISA's check for `RHEL-09-653030`, audit
  record storage capacity. It was unknown before and after the fixes, so both
  runs ended with the playbook's warning that the scan is incomplete.
- The Ubuntu benchmark took almost nine minutes on a VM with two processor
  cores, where the RHEL one took 20 seconds. DISA's `Disable_Slow_Rules`
  profile was not tried.

### Exceptions files made with the vendors' tools

| Step | Result |
| --- | --- |
| `autotailor` on RHEL 9.8, as chapter 9 gives it | Exit status 0. A tailoring file with one profile, `..._profile_stig_site`, that extends `..._profile_stig` and unselects the named rules. |
| `sudo usg generate-tailoring disa_stig tailoring.xml` on Ubuntu | A tailoring file with one profile, `..._profile_stig_customized`, that extends `..._profile_stig`, lists all 230 rules as selected, each under a comment with its STIG ID, and sets 33 values. The file belongs to root, mode 0600. Without `sudo`, `usg` refuses to run. |
| `scripts/summarize_xccdf.py --tailoring` on the controller, Python 3.9 | Read both files: the profile, the profile it extends and the rules left out. |
| **RHEL 9 · STIG audit** with `content/rhel/9/tailoring.xml`, two rules left out | The log named the file, its SHA-256 and the two rules. `notselected` rose from 1063 to 1065; failing rules fell from 267 to 266, CAT I from 10 to 9, because one of the two had been passing. |
| **Ubuntu 24.04 · STIG audit** with `content/ubuntu/24.04/tailoring.xml`, two rules left out | The same lines. `notselected` rose from 409 to 411; failing rules fell from 64 to 62. |
| **RHEL 9 · STIG audit, DISA SCAP file** with `tailoring.xml` in the same folder | `no exceptions file`: the folder's file is for the vendor's content. |
| The same template with `stig_tailoring_file` naming a file that `autotailor --id-namespace mil.disa.stig` made for DISA's benchmark | Used: the one rule it left out, the unknown one, was `notselected`, and the scan had no unknown result. |
| The same with `stig_tailoring_file` naming the vendor profile's file | Refused before scanning: `Its profile ..._stig_site extends ..._profile_stig, and this run scans with xccdf_mil.disa.stig_profile_MAC-1_Classified.` |
| `stig_tailoring_file` naming a file that does not exist | Refused before scanning. |

`stig_tailoring_file` was passed as an extra variable of the task through the
API.

### Fixes with an exceptions file

| Run | Before | After | The rules left out |
| --- | --- | --- | --- |
| **Ubuntu 24.04 · STIG apply, allow required reboot**, `usg fix --tailoring-file`, two rules left out | 62 failing: CAT I 4, CAT II 52, CAT III 6 | 10 failing after the reboot: CAT I 2, `UBTU-24-102000` and `UBTU-24-600030`, CAT II 8. 4 min 17 s. | `vlock_installed` and `kernel_module_usb-storage_disabled`: the package was still not installed and no modprobe rule was written, while other fixes, such as AIDE, were applied. |
| **RHEL 9 · STIG apply, allow required reboot** with Limit set to the controller itself, `oscap xccdf eval --remediate --tailoring-file`, four rules left out | 264 failing: CAT I 9, CAT II 236, CAT III 15, without a category 4 | 12 failing: CAT I 2, `RHEL-09-212020` and `RHEL-09-671010`, CAT II 9, CAT III 1. 3 min 6 s. | `package_s-nail_installed` and `package_libreswan_installed`: neither package was installed, while `fapolicyd`, `usbguard` and `aide` were. `grub2_password` and `partition_for_tmp` have no fix to skip. |

**The controller as its own target.** The RHEL run did not restart the
machine: the boot ID was unchanged, the task ended `success` with its second
scan, and its last message said
`vendor remediation applied without the reboot you approved: rhel9-vendor01 is the controller this run comes from`.
The controller was then restarted from its terminal with
`sudo systemctl reboot`. It came back with Semaphore, PostgreSQL, `fapolicyd`
and `usbguard` active and SELinux enforcing; the fixes had set the `FIPS:STIG`
crypto policy. `fapolicyd` ran with `permissive = 0`. **Ping** then passed on
both machines, **RHEL 9 · STIG audit** again reported 12 failing rules with
the same two in CAT I, and the DISA scan ran as listed above. The audit log
held no denial from `fapolicyd`, which a later run showed to prove little:
`fapolicyd` does not watch the Semaphore service by default, and it denied the
administrator's own Git and Python commands without an audit record. The
[hardened-controller record](2026-11-hardened-controller.md) has that run.

### What the run changed

- **`usg` writes the file as root.** Chapter 9 now hands it to the
  administrator's account, shows the `sed` line that unselects a rule, and
  says how to bring the file to the controller.
- **`usg` restates every value of the profile.** The log line said the file
  `changes 33 value(s)` when nothing had been changed. It now says `sets`, and
  the description's key is `values_set`.
- **A refusal ran two sentences together** when the file could not be read.
  The reader's error now ends with a period.
- **STIG apply and its own controller.** The guard described above was added
  before the run, after the patch playbook's same fault in the
  [upgrade record](2026-11-controller-upgrade.md), and ran here for the first
  time.

The two wording fixes reached the running controller through
`controller/update-controller.sh --apply`, with the DISA files and the
exceptions files in the lab folder's `content/` folder, and the later runs
above used them.

### Review after the run

An independent review of the changed playbooks and the script followed the
run. These came from it:

- **On Ubuntu an exceptions file could decide the baseline.** With
  `stig_usg_profile` set to anything but `disa_stig`, the file's base profile
  was not checked, and `usg` takes the profile from the file. The file is now
  checked against the STIG profile under `disa_stig`, `stig` or `stig-v1r1`,
  and refused with any other `usg` profile.
- **The findings file guarded two of its six columns** against a spreadsheet
  that runs a cell as a formula. Every cell comes from the scanned machine's
  results, so every cell is guarded now, also behind white space or a tab.
- **A file could change a rule without it being named:** `selected="0"`, which
  XML reads as false, and `refine-rule`. Both are counted, and refined rules
  are named in the log.
- **Three messages named the wrong cause:** a short `stig_content_profile`
  beside a folder with one benchmark, a profile ID in the file that is no
  XCCDF ID, and a rule name that contains `_rule_` or `_group_`, which lost
  its beginning.
- **An encoding Python does not know** ended the script with a traceback; it
  is one line now. An earlier copy of the script in the lab folder, which
  does not know `--findings`, is named as the cause of a missing summary.

These changes are in the checks on the controller and in the script. The
commands that run on a target are the ones of the live run. The changed tasks
then ran under ansible-core 2.21.1 on a workstation, taken unchanged from
`playbooks/tasks/stig_scan.yml`, with the exceptions files that `autotailor`
and `usg` wrote in the live run and the RHEL results kept from September:
eleven cases, the five refusals among them. They did not run on the lab
machines again.

### Seen and left as it is

- After the vendor's fixes, `sssd.service` was a failed unit on Ubuntu and
  `rngd.service` on RHEL, a VM without a hardware random number generator.
  Both come from the vendor's remediation.
- The administrator's sudo with a password and the automation account's
  key and sudo kept working on both machines after the fixes.

## The summary on results kept from September

The changed `scripts/summarize_xccdf.py` was also run on the results that the
[September run](2026-09-onboard-stig.md) fetched from RHEL 9.8, AlmaLinux 9.8
and Ubuntu 24.04.

| Results | Release line | Failing rules: CAT I, II, III, without a category |
| --- | --- | --- |
| RHEL 9.8 audit | `STIG release V2R9: profile 'DISA STIG for Red Hat Enterprise Linux 9' in 'Guide to the Secure Configuration of Red Hat Enterprise Linux 9' 0.1.82` | 10, 232, 16, 4 |
| AlmaLinux 9.8 audit | `STIG release V2R9: profile 'DISA STIG for AlmaLinux OS 9' ... 0.1.82` | 10, 234, 21, 3 |
| Ubuntu 24.04 audit | `STIG release V1R1: profile 'Canonical Ubuntu 24.04 LTS Security Technical Implementation Guide (STIG) V1R1' ... 0.1.78` | 4, 58, 5, 0 |
| RHEL 9.8 after the fixes and the reboot | the same as the RHEL audit | 3, 9, 3, 0 |

The totals are those of the September record: 262, 268 and 67 failing rules
before, 15 on RHEL afterwards.

## Offline checks

`python3 scripts/validate.py` and the 458 offline tests pass; ansible-core
2.21.1 accepted the syntax of the shared and the per-system STIG playbooks.
The tests added for this change cover:

- the release line for vendor content, for a DISA benchmark, for content that
  states no release and for a result without its benchmark;
- the categories, the CAT I list and the findings file's order and columns,
  with and without STIG IDs in the content;
- an exceptions file: its description, the files `autotailor` and `usg` wrote
  in the live run, `selected="0"` and `refine-rule`, the refusals (not a
  tailoring file, no profile or several, no base profile, a profile ID that
  is no XCCDF ID, a base profile other than the run's on Enterprise Linux, on
  Ubuntu and with a DISA file, another `usg` profile than the STIG's), the
  default file in a system's folder, and the `oscap` and `usg` commands with
  and without it, for the scans and for the fixes;
- the findings file's guard on every cell, and an unknown encoding;
- a content folder with one, no and two benchmarks;
- that **STIG apply** tells its own controller apart by the boot ID, skips its
  reboot and says so;
- that no message of the STIG playbooks carries a stray line break, and that
  the summary script keeps to the Python 3.9 of Enterprise Linux 9.

## Not established

- **AlmaLinux and Rocky Linux with these changes.** No scan ran on either.
  Their exceptions files are made from `ssg-almalinux9-ds.xml` and
  `ssg-rl9-ds.xml` with the same `autotailor` command, which was not run on
  them.
- **A RHEL target that is not the controller.** The RHEL fixes with an
  exceptions file ran on the controller itself, where the reboot is left
  alone. The reboot inside the task and the scan after it ran with an
  exceptions file on Ubuntu only.
- **An Ubuntu controller with these changes.** The controller of this run was
  RHEL 9.8; the Ubuntu controller is covered by the offline tests only.
- **A hardened controller beyond these jobs,** in this run. The update tools,
  the onboarding command and an installation on a machine that is already
  hardened ran the same day; see the
  [hardened-controller record](2026-11-hardened-controller.md).
- **The changes after the review on a machine.** They ran under real Ansible
  on a workstation, as said above, and not from Semaphore against a target.
- **An exceptions file that changes a value or refines a rule.** Every file of
  the live run only unselected rules; what `oscap` and `usg` do with a
  `refine-rule` was not run.
- **`stig_tailoring_file` from the CLI with `-e`,** and from a variable group
  in the UI. It was passed through the API as an extra variable.
- **RHEL 9.9 and a later `scap-security-guide`.**
- **A Rocky Linux STIG from DISA.** None was looked for beyond the earlier
  records, which verified none.
- **Import into DISA's STIG Viewer.** The findings file is a CSV for people;
  it is not a checklist file.
