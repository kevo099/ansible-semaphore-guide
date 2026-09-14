# 9. Optional CIS and DISA STIG practice

[Previous: operations](08-operations.md) · [Next: recovery](10-recovery.md)

## Goal

Learn to select a specific security baseline, capture an honest assessment,
review remediation and verify the result after reboot.

Use separate disposable security-practice targets or restore the same clean
tools baseline between experiments. Leave the Ansible/Semaphore controller
available as a recovery and execution platform. The five starter lessons do
not apply CIS or STIG hardening.

## Choose the question you are testing

| Choice | What it means |
| --- | --- |
| CIS Level 1 | A baseline profile whose intended operational impact is generally lower than Level 2; still review its actual settings. |
| CIS Level 2 | Additional restrictions for environments able to support them. It needs explicit suitability testing. |
| DISA STIG | A separate security target with its own requirements, often relevant to defense environments. It is not simply “CIS Level 3.” |
| Published profile | The selected vendor profile without your own exclusions. Record any tailoring bundled by the vendor as well. |
| Locally tailored profile | A separately identified profile containing documented site settings or deviations. It is not an unchanged published benchmark. |

Choose the baseline required by the system owner and its use case. A CIS scan
of a STIG-hardened machine measures overlap between those states; it is not a
clean CIS remediation experiment. Benchmark version and operating-system
version matter, so record them with the results.

## Preparation and recovery

Before applying hardening:

1. Confirm the exact guest, OS, image, benchmark package and profile.
2. Preserve a clean tools baseline and an independent backup when required.
3. Verify console access, SSH host-key trust, the administrator's password and
   the automation account's password-backed sudo.
4. Read the profile's storage, bootloader, firewall, authentication, crypto,
   logging and external-service requirements.
5. Capture a before-scan, then review the planned remediation and its limits.

Hardening can change SSH algorithms, PAM, sudo, firewall access and boot
behavior. Passwordless or incomplete account setup can stop working after
remediation. A snapshot on the same storage is useful for an experiment, but
is not recovery from losing that storage.

## RHEL 9: native packages and Ansible content

**Where: a registered RHEL 9 security-practice target.** Use your own valid
subscription and keep registration details private.

```bash
sudo dnf install -y openscap-scanner scap-security-guide ansible-core rhc-worker-playbook
rpm -q openscap-scanner scap-security-guide ansible-core rhc-worker-playbook
oscap info /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
ls /usr/share/scap-security-guide/ansible/rhel9-playbook-*.yml
```

Find the exact desired profile in the installed content. For example,
`cis_server_l1` and `stig` may have corresponding packaged playbooks. Do not
substitute a different profile if your requested one is absent.

For a CIS Level 1 experiment, enter a root shell on that disposable target:

```bash
sudo -i
umask 077
benchmark_profile=cis_server_l1
benchmark_work=/var/log/benchmark-practice-cis
install -d -m 0700 "$benchmark_work" /var/tmp/ansible-benchmark
cd "$benchmark_work"
cp "/usr/share/scap-security-guide/ansible/rhel9-playbook-$benchmark_profile.yml" reviewed-playbook.yml
export ANSIBLE_COLLECTIONS_PATH=/usr/share/rhc-worker-playbook/ansible/collections/ansible_collections/
export ANSIBLE_REMOTE_TMP=/var/tmp/ansible-benchmark
ansible-playbook -i localhost, -c local --syntax-check reviewed-playbook.yml
sha256sum reviewed-playbook.yml /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
oscap xccdf eval --fetch-remote-resources \
  --profile xccdf_org.ssgproject.content_profile_cis_server_l1 \
  --results before.xml --report before.html \
  /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
```

Inspect the report and exit status. OpenSCAP commonly returns 2 when it found
noncompliant rules; distinguish those findings from scanner errors and missing
remote resources. The `--fetch-remote-resources` option requires access to the
content's referenced resources, so record and validate what was used.

Read the copied playbook, its variables and the vendor's prerequisites. Only
after review and recovery preparation, apply it:

```bash
ansible-playbook -i localhost, -c local reviewed-playbook.yml > apply.log 2>&1
```

Review the full result. Reboot the selected target as a separate controlled
step, verify console/SSH/sudo, and repeat the same scan into `after.xml` and
`after.html`. Reestablish shell variables and the collection/temp-directory
exports in a new session before repeating commands. Preserve the original
results rather than overwriting them.

RHEL System Roles are a separate body of reusable administration content;
installing them does not mean that an SSG benchmark has been applied. The
packaged SSG workflow and required collections are described in
[Red Hat's hardening guide](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html-single/security_hardening/index).

### A separate STIG experiment

Restore the clean tools baseline, then select the installed `stig` playbook
and its matching profile. Follow the vendor's FIPS, account and storage
requirements before applying changes. A post-install FIPS flag does not prove
that all keys were generated under the required conditions or that the entire
deployment is validated. See [Red Hat's FIPS-mode guidance](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/security_hardening/switching-rhel-to-fips-mode_security-hardening).

## Ubuntu: Canonical Ubuntu Security Guide

**Where: a separate Ubuntu security-practice target.** Attach Ubuntu Pro using
your own supported account workflow. Do not put a subscription token in a
playbook or command transcript. Enable and install the tool through its
supported channel:

```bash
sudo pro enable usg
sudo apt-get update
sudo apt-get install -y usg
usg --help
```

Inspect the actual installed packages and available content. Packaging and
profile aliases can differ between releases. On a 24.04 channel using the
`usg-benchmarks` layout, inspect its public benchmark metadata:

```bash
dpkg-query -W usg usg-benchmarks
cat /usr/share/usg-benchmarks/benchmarks.json
```

If that package/layout does not exist, use your release's supported package
inventory and documentation. Do not install a similarly named older benchmark
package just to satisfy the example. Canonical's documentation uses aliases
such as `cis_level1_server` and `disa_stig`; a versioned channel may expose
IDs such as `cis_level1_server-v1.0.0` or `stig-v1r1`. Select an ID actually
listed by your installed content and record the associated version.

On a channel listing the first versioned CIS ID and supporting the shown
output options, an assessment workflow is:

```bash
sudo -i
umask 077
usg_profile=cis_level1_server-v1.0.0
install -d -m 0700 /var/log/benchmark-practice-cis
cd /var/log/benchmark-practice-cis
usg audit "$usg_profile" --results-file before.xml --html-file before.html
usg generate-fix "$usg_profile" --output reviewed-fix.sh
bash -n reviewed-fix.sh
sha256sum reviewed-fix.sh
```

Read the generated content. `bash -n` checks syntax, not its operational safety.
If your installed CLI uses different output options, consult `usg audit --help`;
the standard audit also writes reports beneath `/var/lib/usg`.

After review, a recovery checkpoint and a deliberate hardening decision:

```bash
usg fix "$usg_profile"
```

Reboot the selected guest, check access and services, and audit again into
new output files. Keep CIS and STIG experiments separate. The STIG path also
needs the supported FIPS package stream and a usable administrative password;
follow [Canonical's STIG prerequisites](https://documentation.ubuntu.com/security/compliance/usg/disa-comply/).

For organization-specific values, generate and review a separate tailoring
file, then pass it explicitly to the audit/fix commands. Record exclusions and
who owns their decision. [Canonical's tailoring guide](https://documentation.ubuntu.com/security/compliance/usg/disa-customize/)
describes the mechanism; editing a tailoring file does not itself approve risk.

## AlmaLinux: inspect its native content

AlmaLinux may package content that differs from the upstream archive or from
RHEL's package, even when a release label looks similar:

```bash
sudo dnf install -y openscap-scanner scap-security-guide
rpm -q openscap-scanner scap-security-guide
oscap info /usr/share/xml/scap/ssg/content/ssg-almalinux9-ds.xml
```

Start with an assessment of an available Alma profile. Do not point an Alma
guest at RHEL's datastream to obtain a preferred label. If a generated vendor
fix behaves unexpectedly, preserve the evidence and investigate that exact
content. Do not mask reboot commands, disable SELinux or suppress a finding
simply to get a green task.

## Interpret results and preserve evidence

Keep these items privately for each run:

- OS and package versions; benchmark/profile IDs; any tailoring and its hash.
- Before XML/HTML, the reviewed remediation, its hash and execution log.
- Post-reboot XML/HTML and separate SSH/sudo/application checks.
- Failed rules, manual checks, scanner errors and unresolved prerequisites.

You can summarize a retained XCCDF result with the included read-only helper:

```bash
python3 scripts/summarize_xccdf.py /path/to/after.xml
```

If the XML contains multiple assessments, supply an exact `--result-id`.
The helper rejects an empty assessment and distinguishes result instances
from unique rule IDs. One rule can produce many checks, even with mixed
outcomes, so dividing raw pass counts by unique rules is misleading.

Its exit code 0 means the selected XML parsed without error/unknown outcomes,
**not that every control passed**. Exit 2 flags error/unknown outcomes; exit 1
indicates invalid input or ambiguous selection. Read the counts and original
report. No compliance percentage is calculated.

A first remediation can install packages that make additional checks
applicable. A second scan can therefore expose failures that were previously
not applicable. Investigate the transition instead of assuming the host became
less secure merely because the raw fail count increased.

## Concept

The deliverable is a reproducible configuration with evidence and understood
exceptions. A completed automation task, an enabled FIPS flag and a benchmark
certificate are different claims and require different evidence.
