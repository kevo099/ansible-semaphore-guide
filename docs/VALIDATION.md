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

## Enterprise Linux 9 installer: what was exercised

The `install-controller-el9.sh` path was applied to a fresh RHEL 9.8 x86_64
cloud VM with vendor repositories available, twice: once while the seeding
helper was being corrected, then once more from a new image with the final
scripts in a single run. Observed on that image:

- The installer completed the runtime, database, application, service account,
  key pair, lab folder and API seeding without manual steps; the readiness
  check reported every item true, both listeners loopback-only and SELinux
  enforcing.
- A task started from the seeded **Ping** template ran from the local lab
  folder, read the file inventory, passed the playbooks' scope guard because
  the seeded templates pass `--limit lab` as a CLI argument, accepted the
  target's host key under strict checking, and stopped at the target with
  `Permission denied (publickey)` until the automation key was authorized
  there. The template `limit` field alone did not produce `--limit` on this
  release, which is why the seeder uses the argument list.
- `add-target.sh` added a host only when the scanned key matched the console
  fingerprint, and changed neither file on a mismatch.

Not established by this: AlmaLinux and Rocky images, RHEL without working
repositories, a controller restore onto this path, or images newer than the
one tested. Vendor cloud images may also carry pending updates; the installer
does not reboot.

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
