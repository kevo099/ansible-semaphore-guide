# Validation and limits

[Back to the guide](../README.md)

## What was exercised

The underlying lab workflow was exercised with an Ubuntu 24.04 controller and
Ubuntu 24.04/AlmaLinux 9 targets: native Semaphore with PostgreSQL, authenticated
CLI/UI jobs, SSH trust, password-backed sudo, configuration apply/repeat, drift
repair and controlled patch/reboot checks. Separate RHEL and Ubuntu vendor
benchmark experiments informed the troubleshooting and assessment guidance.

This public edition generalizes those patterns. It contains no private test
inventories, credentials, machine identities or recovery artifacts. **The new
generalized installer has not been applied to a fresh VM as part of this
publication.** Its static checks do not establish end-to-end installation,
fresh-controller restore, or compatibility with every image/package revision.

Before relying on it, perform the guide on disposable VMs and record your own
results. Optional Azure, high-availability and independently stored backup
designs require their own qualification. Vendor hardening results depend on
the exact image, packages, profile, tailoring and external prerequisites.

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
git diff --check
```

The validator checks Python/Bash/YAML syntax, shell/data examples in Markdown,
local links and selected publication boundaries. It reports rule names and file
locations without echoing a detected credential. It is deliberately conservative
about real addresses, account identifiers and private runtime files.

The eight unit tests cover unique locally generated secrets, refusing file
overwrite/symlinks, and XCCDF assessments containing repeated rules, multiple
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
