# Validation record: September 2026 core verification

[Back to validation and limits](../VALIDATION.md)

This page preserves, unchanged, the verification of the core guide recorded
up to 26 September 2026, when the runtime pin was ansible-core 2.20.8 and then
2.20.9. Chapter references are to the chapters as they were then; chapter 3b's
exposure, STIG and repository-migration sections have since moved to
[browser access](../appendices/browser-access.md),
[chapter 9](../09-security-benchmarks.md#the-seeded-stig-templates) and
[the Git migration appendix](../appendices/git-migration.md) with their
commands unchanged. The current summary and the current list of what is not
established are in [validation and limits](../VALIDATION.md).

## Fresh-VM verification

In September 2026 the commands of chapters 3 to 8 and 10, chapter 2's guest
checks and chapter 9's AlmaLinux content inspection were run on newly created,
disposable Proxmox VMs imported from official cloud images, after checking the
publishers' checksums and signatures: Ubuntu 24.04.5 and AlmaLinux 9.8. Three
controllers were built: the Ubuntu installer path, the Ubuntu manual path with
each documented block run as written, and the Enterprise Linux 9 seeded
installer on AlmaLinux. Two fresh targets, Ubuntu 24.04.5 and AlmaLinux 9.8,
were managed from them.

The last five rows below record later runs. Chapter 9's RHEL and Ubuntu
Security Guide commands ran on two existing registered guests, which were
restored to their pre-test checkpoints afterwards; a seeded controller was
also installed on the RHEL guest. New VMs then tested Rocky Linux 9.8, from
Rocky's signed cloud image: a seeded Rocky controller managing a Rocky target
and an AlmaLinux 9.8 target.

Tested versions: Semaphore Community 2.19.12, PostgreSQL 16, and ansible-core
with every Python dependency pinned in
[`requirements-controller.txt`](../../requirements-controller.txt). The September
runs used ansible-core 2.20.8 and installed it by version only; every
controller install resolved exactly the set that file pins. On 26 September
2026 the pin moved to 2.20.9, which resolves to the same dependency set; the
last row records its recheck. The runs above covered the guide up to
tag `v1.1.0`. The changes after it passed the
[offline checks](../VALIDATION.md#repeat-the-offline-checks). The last row records a recheck
on the registered guests at commit `213a90b`, and a second recheck at commit
`ffabdda` covered the changes made after it. Only `expose-semaphore.sh`'s
message for a VM without an IPv4 route has passed nothing but the offline
checks.

| Area | Result |
| --- | --- |
| Controller installation | All three fresh-VM builds passed every readiness check, with the application and database on loopback only and SELinux enforcing on AlmaLinux. The later seeded controllers on RHEL and Rocky Linux also reported ready. The Ubuntu installer's controller kept its configuration and jobs across a reboot. |
| Access (chapter 4) | Host keys were accepted only after comparing fingerprints. `sudo -n` was refused, `sudo -v` accepted and Ansible `-b -K` returned uid 0 on both targets. |
| CLI lessons (chapter 5) | All five lessons on both OSes: previews, applies, `changed=0` repeats, drift repair, a page change without a handler, and refusals of a missing limit, invalid user names and a string reboot flag. The default patch left a required reboot pending; JSON `true` rebooted. |
| Semaphore (chapter 6) | The project, inventory, repository, variable groups and a template were created and run in the UI. All 16 templates then succeeded on clean targets for both OSes, including drift repair and the reboot policy. |
| Git and Vault (chapter 7) | An exercise branch in a reviewed local repository reached the target, and the normal ref restored it. One CLI run used each host's own Vault-encrypted sudo password. Semaphore used such files through a Vault key only from the Enterprise Linux controller's lab folder (chapter 3b); a template reading them from a Git repository or with a Static inventory was not run. |
| Recovery (chapter 10) | The capture's checksums matched after copying it off the controller. An Ubuntu controller's capture, restored onto an isolated Ubuntu replacement, recovered all 46 tables with matching row counts. While isolated, a job failed at the network layer. With one target allowed, Ping and a check-mode Baseline decrypted the restored SSH and sudo credentials. |
| Seeded EL9 path (chapter 3b) | `add-target.sh` refused a mismatched fingerprint and a duplicate host. The lessons succeeded with both sudo-credential options. Each exposure mode opened only its intended port. On AlmaLinux the vendor `stig` profile went from 273 to 24 failing rules after one remediation pass without a reboot, with no scanner errors. Automation access and sudo still worked afterwards. |
| Registered vendor guests (chapters 3b, 5 and 9) | On a registered RHEL 9.8 guest and an Ubuntu 24.04.5 guest attached to Ubuntu Pro, chapter 9's RHEL and USG inspection and CIS assessment commands ran as written: package and profile listing, the CIS preparation and before-scan, and USG fix-script generation. The manual CIS remediation was not applied. From the command line, all five lessons ran on RHEL: Baseline, Users and Webserver reported `changed=0` on repeat, and Patch left its required reboot to the operator. STIG audit assessed both hosts in one run; the Ubuntu Security Guide path also ran through Semaphore on a seeded controller installed on that RHEL guest. STIG apply with the approved reboot took Ubuntu from 64 to 10 failing rules and RHEL from 266 to 13, with no scanner errors, and automation access and sudo worked afterwards. Both guests were then restored to their pre-test checkpoints. |
| Rocky Linux 9.8 (chapters 3b, 4 and 9) | The seeded installer ran on a Rocky controller. Chapter 4's target steps, with the seeded key, prepared an AlmaLinux and a Rocky target, and the seeded templates managed both, including an approved-reboot patch on AlmaLinux. On Rocky, Baseline, Users and Webserver reported `changed=0` on repeat and Patch left its required reboot to the operator; STIG audit used Rocky's own `ssg-rl9-ds.xml`, and STIG apply with the approved reboot took failing rules from 262 to 26 with no scanner errors. Access and sudo worked afterwards. With a VirtIO RNG device, `rngd`, which the Rocky image enables by default, stayed healthy after STIG apply. A template cloning this repository at tag `v1.1.0` ran Baseline on Rocky; at `v1.0.0`, which predates Rocky support, the preflight refused the host. |
| Recheck of the later changes (chapters 3, 3b, 7 and 10) | On the two registered guests, restored to their checkpoints afterwards. With the Ubuntu Pro guest as controller: the Ubuntu installer, whose virtual environment matched `requirements-controller.txt` exactly; readiness with the UI on loopback, behind https and on loopback again, with port 80 closed and a warning when a reused certificate named another address; chapter 7's bare repository, which Ubuntu's Git 2.43 refused as dubious ownership without the `safe.directory` entry; and chapter 10's capture. With the RHEL guest as seeded controller managing the Ubuntu guest: `--lab-dir` paths under `/home`, `/tmp` and `/var/lib/semaphore` and a relative path were refused before any change; the lab folder's `.gitignore` left no inventory tracked; `add-target.sh` accepted a section header with a comment and refused a duplicate; Ping, Baseline preview and a STIG audit that printed its summary succeeded; Dry Run was refused for both STIG templates before connecting; each exposure mode worked; 3b's migration of a folder that tracked its inventory left Ping working; and chapter 10's capture included the PostgreSQL settings and the lab folder. RHEL's Git 2.52 read the bare repository without the entry. |
| Second recheck (chapters 3b, 4, 5 and 10) | At commit `ffabdda` on the same registered guests, restored afterwards. Certificates with a fixed common name and the address only in the subjectAltName were accepted by a strict TLS client for an IP address, a DNS name and an 88-character name, and a mismatched name was rejected. With 3b's Vault option, Ping from the lab folder failed without the Vault password; with `--ask-vault-pass` and no `-K`, Ping and a check-mode Baseline succeeded. 3b's publish review, untracking of a private file and one-commit history pushed a single commit without the inventory, the private file or a file deleted earlier. Chapter 10 ran end to end on Enterprise Linux: a capture taken with the UI in `http` mode, checked off the controller, was restored onto the same guest after rolling it back to its checkpoint. The pinned runtime matched the capture, `config.json` was reset to loopback, all 46 tables had the same row counts, the target was blocked while Semaphore started, and then Ping and a check-mode Baseline decrypted the restored credentials. The restored PostgreSQL was not enabled at boot, which chapter 10 now covers. |
| Recheck of ansible-core 2.20.9 and the seeder (chapters 3, 3b and 6) | At commit `9104b30` on the same registered guests, restored afterwards. Both installers installed ansible-core 2.20.9 with exactly the pinned set and passed readiness. The seeded templates carried their variable groups through `environment_ids`: only the two "allow required reboot" templates use **Allow required reboot**. Against the Ubuntu Pro guest, Ping, Baseline preview, Baseline apply and a `changed=0` repeat, and both patch templates succeeded. The guest did not need a reboot, so the approved-reboot path was not exercised in this run. |

### Fixed during the verification

- A Semaphore sudo credential's **Username** becomes `--become-user`. The
  earlier instruction to enter `svc_ansible` there made privileged tasks fail
  as soon as a change was needed.
- The seeded project had no sudo credential, so its become templates failed
  with `Missing sudo password`.
- STIG audit stopped at an Ubuntu host without `usg` before any Enterprise
  Linux host was assessed, and STIG apply could select every host at once.
- The template **Limit** option does pass `--limit` in this release; an earlier
  note here said otherwise. The seeder now uses it.
- `--mode https` on Enterprise Linux also opened nginx's default plain-HTTP site
  on port 80, and leaving https left nginx running.
- The EL9 path pinned the Ed25519 host key, which an AlmaLinux target stopped
  offering after vendor STIG remediation.
- Rewriting the service's known-hosts file with `ssh-keygen -R`, creating a bare
  repository with shared-repository settings, and creating Vault files could
  each leave files the service cannot read. The readiness check and chapters 3b
  and 7 now cover them.

### Not established at the time

- FIPS mode. On RHEL, AlmaLinux and Rocky Linux the vendor STIG sets the
  `FIPS:STIG` crypto policy. On RHEL and AlmaLinux `fips-mode-setup --check`
  then reported that FIPS mode is not enabled; Rocky Linux's FIPS mode and
  host-key offer were not checked. Ubuntu was not switched to FIPS kernels.
- Chapter 9's manual CIS remediation (the packaged RHEL playbook and `usg fix`
  with a CIS profile), its reboot and after-scan. Vendor STIG remediation was
  applied only through `stig-apply.yml`.
- Repeated remediation until no further rule changes.
- Enterprise Linux releases other than 9.8, as controller or target. The EL9
  installer's 9.4 minimum is where `python3.12` and the `postgresql:16` stream
  first appear, not a tested release.
- More than one parallel Semaphore task, schedules, integrations, offsite
  backup copies and high availability.
- Clicking every UI form: the remaining templates and keys were created through
  the same API after their forms were checked in the browser.
- The optional Azure chapter, chapter 2's manual ISO installation, editing
  through VS Code Remote SSH in chapter 7, and the troubleshooting chapter's
  diagnostics as a separate exercise.

## Earlier checks

The first publication was checked offline only: syntax, lint, unit tests, the
repository validator and a secret scan. Its patterns came from a separately
exercised private lab.

The Enterprise Linux 9 installer was first applied to a fresh RHEL 9.8 x86_64
cloud VM with vendor repositories. The installer, seeding, `add-target.sh`,
`--mode https` and a STIG audit of that controller completed there. That run
concluded that the template Limit field did not produce `--limit`; the seeder
had sent a field this release ignores, and the Limit option itself works.
