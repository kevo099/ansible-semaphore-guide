# Validation and limits

[Back to the guide](../README.md)

## Fresh-VM verification

In September 2026 the commands of chapters 3 to 8 and 10, chapter 2's guest
checks and chapter 9's AlmaLinux content inspection were run on newly created,
disposable Proxmox VMs imported from official cloud images, after checking the
publishers' checksums and signatures: Ubuntu 24.04.5 and AlmaLinux 9.8. Three
controllers were built: the Ubuntu installer path, the Ubuntu manual path with
each documented block run as written, and the Enterprise Linux 9 seeded
installer on AlmaLinux. Two fresh targets, Ubuntu 24.04.5 and AlmaLinux 9.8,
were managed from them.

The last three rows below record later runs. Chapter 9's RHEL and Ubuntu
Security Guide commands ran on two existing registered guests, which were
restored to their pre-test checkpoints afterwards; a seeded controller was
also installed on the RHEL guest. New VMs then tested Rocky Linux 9.8, from
Rocky's signed cloud image: a seeded Rocky controller managing a Rocky target
and an AlmaLinux 9.8 target.

Tested versions: Semaphore Community 2.19.12, PostgreSQL 16, and ansible-core
2.20.8 with every Python dependency pinned in
[`requirements-controller.txt`](../requirements-controller.txt). The runs
installed ansible-core by version only; every controller install resolved
exactly the set that file now pins. The runs above covered the guide up to
tag `v1.1.0`. The changes after it passed the
[offline checks](#repeat-the-offline-checks), and the last row records a
recheck of the changed scripts on the registered guests.

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

### Not established

- FIPS mode. On RHEL, AlmaLinux and Rocky Linux the vendor STIG sets the
  `FIPS:STIG` crypto policy. On RHEL and AlmaLinux `fips-mode-setup --check`
  then reported that FIPS mode is not enabled; Rocky Linux's FIPS mode and
  host-key offer were not checked. Ubuntu was not switched to FIPS kernels.
- Chapter 9's manual CIS remediation (the packaged RHEL playbook and `usg fix`
  with a CIS profile), its reboot and after-scan. Vendor STIG remediation was
  applied only through `stig-apply.yml`.
- Repeated remediation until no further rule changes.
- Chapter 10's restore on an Enterprise Linux controller; its capture ran there.
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

## Repeat the offline checks

**Where: your development working copy.** These checks parse source and run
unit tests; they do not install the controller or connect to managed hosts.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/validate.py
.venv/bin/python -m unittest discover -s tests -v
for playbook in playbooks/*.yml; do
  .venv/bin/ansible-playbook -i inventories/lab.ini.example --syntax-check "$playbook"
done
.venv/bin/ansible-lint --offline playbooks/
for installer in scripts/install-controller.sh scripts/install-controller-el9.sh; do
  bash "$installer" | grep '^Plan:'
  bash "$installer" --plan >/dev/null
done
git diff --check "$(git hash-object -t tree /dev/null)"
```

The installer loop confirms that an installer run with no arguments prints its
plan. The last command compares every tracked file, including uncommitted
edits, with an empty tree, so it rejects whitespace errors and leftover
conflict markers anywhere in the repository.

The validator checks Python/Bash/YAML syntax, shell/data examples in Markdown,
local links and their heading anchors, and selected publication boundaries. It
reports rule names and file locations without echoing a detected credential. It
is deliberately conservative about real addresses, account identifiers and
private runtime files.

The unit tests cover unique locally generated secrets, refusing file
overwrite/symlinks, the Semaphore seeding plan (local repository, file
inventory, scoped templates, preview-only arguments, no key material), the
publication-boundary rules of `scripts/validate.py`, the readiness parsers in
`scripts/check-controller.py`, and the contracts between the lesson playbooks
and the seeder: the accepted distributions and their STIG data streams, the
approval phrase, and the helper scripts the playbooks call. They also cover
XCCDF assessments containing repeated rules, multiple results, missing results
or scanner errors. A parsed assessment can contain failed controls; the parser
never turns successful parsing into a compliance claim.

GitHub Actions runs the same offline checks with read-only repository
permissions, pinned action revisions and no lab/cloud credentials. It
additionally resolves the pinned controller runtime from PyPI, without
installing it. It does not apply the installers, provision VMs or deploy
playbooks.

## Secret review before publishing

Inspect the exact staged files and their history. Run a maintained secret
scanner in addition to the repository's limited boundary checks. For example,
with a verified Gitleaks binary installed locally:

```bash
gitleaks dir . --redact --no-banner
gitleaks git . --redact --no-banner
git diff --cached --stat
git diff --cached
```

The initial publication was checked with Gitleaks and a separate private-detail
review. No scanner can prove the absence of every possible secret. Keep real
inventories, Vault files, generated configurations, job logs and database
backups in your own protected storage. `.gitignore` does not untrack a file or
remove it from previous commits.

## Your live acceptance checklist

1. The fresh controller installs, survives a reboot, and has only the intended
   loopback application/database listeners.
2. The private browser tunnel, login/logout and a real authenticated task work.
3. Both targets pass SSH/Python/sudo checks with strict host verification.
4. Each lesson has the expected preview, apply, immediate repeat and independent
   target checks. Verify reboot policy separately.
5. The wrong inventory/limit or invalid inputs fail before the relevant change.
6. An isolated restore recovers data and encrypted credentials sufficiently to
   run a real task against a disposable recovery target.

Record versions, code refs, expected changes, actual outcomes and unresolved
limitations privately. Link only sanitized findings if you propose a public fix.
