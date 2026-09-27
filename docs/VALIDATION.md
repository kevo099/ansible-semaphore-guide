# Validation and limits

[Back to the guide](../README.md)

This page says what the current release has been verified to do, what it has
not, and how to repeat the checks. The dated records keep the details of each
run; this page only summarizes them.

## Current baseline

| Component | Tested version |
| --- | --- |
| Semaphore | Community 2.19.12, checksum-verified native binary |
| Ansible Core | 2.21.4, with every Python dependency pinned in [`requirements-controller.txt`](../requirements-controller.txt) |
| Controller | Ubuntu Server 24.04; RHEL, AlmaLinux and Rocky Linux 9.8 (seeded installer) |
| Database | PostgreSQL 16 |
| Targets | Ubuntu 24.04, AlmaLinux 9.8, Rocky Linux 9.8 and registered RHEL 9.8 |

## What has been verified

| Scope | Result | Record |
| --- | --- | --- |
| Core guide on fresh VMs (chapters 2 to 10) | Three fresh controllers (Ubuntu installer, Ubuntu manual, seeded AlmaLinux), two fresh targets, all five lessons, the UI templates, Git and Vault, and an isolated restore, on ansible-core 2.20.8; rechecks on registered RHEL and Ubuntu Pro guests and on Rocky Linux 9.8, then on 2.20.9. | [September 2026 core verification](validation/2026-09-baseline.md) |
| ansible-core 2.21.4 | Both installers resolved exactly the pinned set and passed readiness. A seeded RHEL 9.8 controller then seeded eleven templates and ran ten of them against an Ubuntu 24.04 Ubuntu Pro target, including `changed=0` repeats and a STIG apply with the approved reboot. | [2.21.4 requalification](validation/2026-09-community.md#ansible-core-2214-requalification) |
| Semaphore Community features (chapters 14 to 18 and the appendices) | Each capability is classified as working, paid only or not present in 2.19.12, with its live result and limits. | [Community coverage](COMMUNITY-COVERAGE.md) and [the campaign record](validation/2026-09-community.md) |
| New chapters as written | Each new chapter's example files and command blocks were run as written on the campaign controller: inputs, other apps, identity, operations, API and webhooks, task identity, runners, export and syslog. Key rotation, identity providers and the upgrade drill rely on the feature tests. | [Rehearsal](validation/2026-09-community.md#rehearsal-of-the-new-chapters) |
| Reorganized chapters | Chapter 3b's exposure, STIG and repository-migration sections moved to [browser access](appendices/browser-access.md), [chapter 9](09-security-benchmarks.md#the-seeded-stig-templates) and [the Git migration appendix](appendices/git-migration.md) with their commands unchanged. The moves passed the offline checks. | This page |

## Not established

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
- ansible-core 2.21.4 against AlmaLinux, Rocky Linux and RHEL **targets**, the
  Ubuntu manual path, and chapter 10's restore. Those last ran on 2.20.x. The
  2.21.4 lessons ran against an Ubuntu target only.
- Offsite backup copies and high availability.
- Delivery to real Slack, Microsoft Teams, Rocket.Chat, DingTalk, Gotify,
  Telegram or e-mail providers. Notifications were received by local test
  receivers.
- Terraform (the HashiCorp binary) and PowerShell task templates; OpenTofu and
  Terragrunt were tested instead.
- Clicking every UI form. The feature campaign drove Semaphore through its API
  and command line, with the same request bodies the UI sends; the chapters name
  the UI labels of 2.19.12.
- The optional Azure chapter, chapter 2's manual ISO installation, editing
  through VS Code Remote SSH in chapter 7, and the troubleshooting chapter's
  diagnostics as a separate exercise.

## Repeat the offline checks

**Where: your development working copy.** These checks parse source and run
unit tests; they do not install the controller or connect to managed hosts.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/validate.py
.venv/bin/python -m unittest discover -s tests -v
for playbook in playbooks/*.yml examples/semaphore/*.yml; do
  .venv/bin/ansible-playbook -i inventories/lab.ini.example --syntax-check "$playbook"
done
.venv/bin/ansible-lint --offline playbooks/ examples/
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

For the optional chapters, add each feature's own check: a schedule fires at
the time you expect and stops when disabled, an alert reaches your receiver, a
refused API token starts no task, and a runner task shows the runner's host.

Record versions, code refs, expected changes, actual outcomes and unresolved
limitations privately. Link only sanitized findings if you propose a public fix.
