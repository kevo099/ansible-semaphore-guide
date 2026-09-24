# Validation and limits

[Back to the guide](../README.md)

## Fresh-VM verification

In September 2026 every chapter's commands were run on newly created,
disposable Proxmox VMs imported from official cloud images, after checking the
publishers' checksums and signatures: Ubuntu 24.04.5 and AlmaLinux 9.8. Three
controllers were built: the Ubuntu installer path, the Ubuntu manual path with
each documented block run as written, and the Enterprise Linux 9 seeded
installer on AlmaLinux. Two fresh targets, Ubuntu 24.04.5 and AlmaLinux 9.8,
were managed from them. Tested versions: Semaphore Community 2.19.12,
ansible-core 2.20.8 and PostgreSQL 16.

| Area | Result |
| --- | --- |
| Controller installation | All three builds passed every readiness check, with the application and database on loopback only and SELinux enforcing on AlmaLinux. A controller reboot kept its configuration and jobs. |
| Access (chapter 4) | Host keys were accepted only after comparing fingerprints. `sudo -n` was refused, `sudo -v` accepted and Ansible `-b -K` returned uid 0 on both targets. |
| CLI lessons (chapter 5) | All five lessons on both OSes: previews, applies, `changed=0` repeats, drift repair, a page change without a handler, and refusals of a missing limit, invalid user names and a string reboot flag. The default patch left a required reboot pending; JSON `true` rebooted. |
| Semaphore (chapter 6) | The project, inventory, repository, variable groups and a template were created and run in the UI. All 16 templates then succeeded on clean targets for both OSes, including drift repair and the reboot policy. |
| Git and Vault (chapter 7) | An exercise branch in a reviewed local repository reached the target, and the normal ref restored it. One CLI run used each host's own Vault-encrypted sudo password, and Semaphore used them through a Vault key. |
| Recovery (chapter 10) | The capture's checksums matched after copying it off the controller. An isolated replacement controller restored all 46 tables with matching row counts. While isolated, a job failed at the network layer. With one target allowed, Ping and a check-mode Baseline decrypted the restored SSH and sudo credentials. |
| Seeded EL9 path (chapter 3b) | `add-target.sh` refused a mismatched fingerprint and a duplicate host. The lessons succeeded with both sudo-credential options. Each exposure mode opened only its intended port. On AlmaLinux the vendor `stig` profile went from 273 to 24 failing rules after one remediation pass without a reboot, with no scanner errors. Automation access and sudo still worked afterwards. |
| Registered vendor guests (chapters 3b, 5 and 9) | On a registered RHEL 9.8 guest and an Ubuntu 24.04.5 guest attached to Ubuntu Pro, chapter 9's RHEL and USG commands ran as written, including the CIS preparation, before-scan and fix-script generation. All five lessons converged on RHEL. STIG audit assessed both hosts in one run; the Ubuntu Security Guide path also ran through Semaphore on a seeded controller installed on that RHEL guest. STIG apply with the approved reboot took Ubuntu from 64 to 10 failing rules and RHEL from 266 to 13, with no scanner errors, and automation access and sudo worked afterwards. Both guests were then restored to their pre-test checkpoints. |
| Rocky Linux 9.8 (chapters 3b, 5 and 9) | The seeded installer ran on a Rocky controller, and its templates managed an AlmaLinux and a Rocky target. On Rocky, every lesson converged, STIG audit used Rocky's own `ssg-rl9-ds.xml`, and STIG apply with the approved reboot took failing rules from 262 to 26 with no scanner errors; access and sudo worked afterwards. With a VirtIO RNG device the STIG-enabled `rngd` stayed healthy. |

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
- The EL9 path pinned the Ed25519 host key, which the target stops offering
  after vendor STIG remediation.
- Rewriting the service's known-hosts file with `ssh-keygen -R`, creating a bare
  repository with shared-repository settings, and creating Vault files could
  each leave files the service cannot read. The readiness check and chapters 3b
  and 7 now cover them.

### Not established

- FIPS mode. On RHEL, AlmaLinux and Rocky Linux the vendor STIG sets the `FIPS:STIG` crypto
  policy, but `fips-mode-setup --check` then reports that FIPS mode is not
  enabled; Ubuntu was not switched to FIPS kernels.
- Repeated remediation until no further rule changes.
- More than one parallel Semaphore task, schedules, integrations, offsite
  backup copies and high availability.
- Clicking every UI form: the remaining templates and keys were created through
  the same API after their forms were checked in the browser.

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
bash scripts/install-controller.sh --plan
bash scripts/install-controller-el9.sh --plan
git diff --check
```

The validator checks Python/Bash/YAML syntax, shell/data examples in Markdown,
local links and selected publication boundaries. It reports rule names and file
locations without echoing a detected credential. It is deliberately conservative
about real addresses, account identifiers and private runtime files.

The unit tests cover unique locally generated secrets, refusing file
overwrite/symlinks, the Semaphore seeding plan (local repository, file
inventory, scoped templates, preview-only arguments, no key material), and
XCCDF assessments containing repeated rules, multiple
results, missing results or scanner errors. A parsed assessment can contain
failed controls; the parser never turns successful parsing into a compliance
claim.

GitHub Actions runs the same offline checks with read-only repository
permissions, pinned action revisions and no lab/cloud credentials. It does
not run the installer, provision VMs or deploy playbooks.

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
