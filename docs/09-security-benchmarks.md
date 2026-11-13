# 9. Optional CIS and DISA STIG practice

[Previous: operations](08-operations.md) · [Next: learning exercises](12-learning-path.md)

## Goal

Learn to select a specific security baseline, capture an honest assessment,
review remediation and verify the result after reboot.

Use separate disposable security-practice targets or restore the same clean
tools baseline between experiments. Leave the Ansible/Semaphore controller
available as a recovery and execution platform. The five starter lessons do
not apply CIS or STIG hardening.

Both seeded controllers ship the same vendor assessments as two shared
playbooks, [`stig/audit.yml`](../playbooks/stig/audit.yml) and
[`stig/apply.yml`](../playbooks/stig/apply.yml), with one audit and apply
playbook per operating system and version under
[`playbooks/stig/`](../playbooks/stig/) and one Semaphore tab for each; see
[the seeded STIG templates](#the-seeded-stig-templates) near the end of this
chapter. [The security baseline catalog](appendices/security-baselines.md)
compares STIG, CIS and the other common baselines and lists the profile IDs
these playbooks accept. Read the manual sections first so you know what those commands do.

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
The seeded templates take such a file too; see
[leave out rules you have an accepted exception for](#leave-out-rules-you-have-an-accepted-exception-for).

## AlmaLinux and Rocky Linux: inspect their native content

AlmaLinux and Rocky Linux may package content that differs from the upstream
archive or from RHEL's package, even when a release label looks similar:

```bash
sudo dnf install -y openscap-scanner scap-security-guide
rpm -q openscap-scanner scap-security-guide
oscap info /usr/share/xml/scap/ssg/content/ssg-almalinux9-ds.xml
```

On Rocky Linux the data stream is `ssg-rl9-ds.xml`. Its `stig` profile is
titled for RHEL 9: it is the DISA RHEL 9 STIG as Rocky packages it, not a
separate Rocky STIG.

Start with an assessment of an available profile. Do not point an Alma or
Rocky guest at RHEL's datastream to obtain a preferred label. If a generated vendor
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
python3 scripts/summarize_xccdf.py /path/to/after.xml --findings /path/to/after-findings.csv
```

Besides the counts, its JSON names the content the scan measured (`content`,
with the STIG release the content states), counts the failing rules by DISA
severity category (`failed_by_category`: CAT I for `high`, CAT II for `medium`,
CAT III for `low`) and lists the failing CAT I rules (`failed_cat_i`).
`--findings` writes every rule that still needs a reader, with the outcome
`fail`, `error`, `unknown` or `notchecked`, to a CSV file, most severe first:
category, severity, outcome, STIG ID, rule ID and title. The STIG ID comes from
the content. RHEL's, AlmaLinux's and Ubuntu's content name one for nearly every
rule, and DISA's own benchmarks for every rule; Rocky Linux's data stream names
none, so its rows carry the rule ID only. The STIG playbooks write this file
beside each fetched report, as `audit-findings.csv`, `before-findings.csv` and
`after-findings.csv`.

If the XML contains multiple assessments, supply an exact `--result-id`.
The helper distinguishes result instances from unique rule IDs. One rule can
produce many checks, even with mixed outcomes, so dividing raw pass counts by
unique rules is misleading. `result_instances` and `unique_rule_ids` count
every rule-result in the XML, including the rules the profile did not select,
which OpenSCAP and USG report as `notselected`; `selected_result_instances` and
`selected_rule_ids` count only the selected ones. In the October test, the
RHEL 9.8 vendor audit selected 477 of its 1540 rules and Ubuntu's `disa_stig`
230. Compare outcome counts and selected totals between runs, never the raw
totals. The helper exits 1 for an XML without rule-results, and for one in
which every rule-result is `notselected`, as when a profile ID or tailoring
selects nothing.

Its exit code 0 means the selected XML parsed without error/unknown outcomes,
**not that every control passed**. Exit 2 flags error/unknown outcomes; exit 1
indicates invalid input or ambiguous selection. Read the counts and original
report. No compliance percentage is calculated.

After remediation, check `systemctl --failed` and the crypto policy before
trusting the host again. In the verification run, one vendor STIG pass with a
reboot left `sssd.service` failed on Ubuntu 24.04, because no SSSD domain was
configured. The STIG enables `rngd.service`, which failed on a RHEL 9.8 VM with
no hardware entropy source and ran normally on Rocky Linux with a VirtIO RNG
device ([the Proxmox page](platform-proxmox.md#do-give-enterprise-linux-guests-a-virtio-rng)). RHEL and AlmaLinux switched to the
`FIPS:STIG` crypto policy and kept FIPS mode disabled, and AlmaLinux then
offered only RSA and ECDSA host keys. Rocky Linux also switched to `FIPS:STIG`;
its FIPS mode and host-key offer were not checked. Ubuntu's USG accepted the
`disa_stig` profile used by the seeded STIG lessons; that channel's
`benchmarks.json` lists it as an alias of `stig-v1r1`.

Record the content version with every result. The verification used SCAP
Security Guide 0.1.82 on RHEL 9.8 and Rocky Linux 9.8, 0.1.81 on AlmaLinux 9.8,
and the Ubuntu Security Guide profiles `cis_level1_server-v1.0.0` and
`stig-v1r1` on Ubuntu 24.04. Benchmarks move faster than packaged content: by
September 2026 CIS had published Ubuntu 24.04 v2.0.0 and RHEL 9 v3.0.0, and SCAP
Security Guide 0.1.82 aligned its Ubuntu 24.04 STIG profile to V1R5. Report a
result as, for example, "64 failing rules with USG `stig-v1r1`", not "STIG
compliant", and check `benchmarks.json` and the installed `scap-security-guide`
version before comparing results over time.

Every STIG run now prints the release its content states, for example
`STIG release V2R9: profile 'DISA STIG for Red Hat Enterprise Linux 9' in
'Guide to the Secure Configuration of Red Hat Enterprise Linux 9' 0.1.82`.
Compare it with the release DISA lists for the system. On 13 November 2026 the
packaged content and DISA's files of 30 September compared like this
([record](validation/2026-11-stig-content.md)):

| System | What the vendor's `stig` profile is | DISA's current STIG | Compared by STIG ID |
| --- | --- | --- | --- |
| RHEL 9 | Red Hat's SCAP Security Guide 0.1.82, states V2R9 | V2R10, 445 rules | 439 of the 445 have a rule in the profile. Missing: three that V2R10 added, one of them CAT I (`RHEL-09-672055`), and three older ones. Ten of the 439 have no automated check, and 37 no automatic fix. |
| AlmaLinux 9 | The same 481 rules, titled "DISA STIG for AlmaLinux OS 9", states V2R9 | AlmaLinux OS 9 V1R8, 439 rules with `ALMA-09` IDs | The profile names only `RHEL-09` IDs. It is the RHEL 9 STIG applied to AlmaLinux; DISA has no AlmaLinux V2R9. |
| Rocky Linux 9 | The same 481 rules, titled for RHEL 9, states V2R9 | No Rocky Linux STIG was verified | The data stream names no STIG IDs, so its results list rules by rule ID. |
| Ubuntu 24.04 | Ubuntu Security Guide 24.04.8, profile `stig-v1r1`, states V1R1 | V1R7, 195 rules | Not compared rule by rule. The release alone is six behind. |

The vendor's profile automates more of the STIG than DISA's own SCAP benchmark,
which checks 393 of the 445 RHEL 9 rules, and it carries fixes, which DISA's
does not. It follows DISA by one release or more, and on AlmaLinux and Rocky
Linux it is the RHEL STIG. Where an assessor names a release, scan with DISA's
file for that release as well and read the manual rules by hand.

A first remediation can install packages that make additional checks
applicable. A second scan can therefore expose failures that were previously
not applicable. Investigate the transition instead of assuming the host became
less secure merely because the raw fail count increased.

## The seeded STIG templates

Both seeded controllers, Ubuntu and Enterprise Linux
([Stage 1](stage-1-controller.md)), organize the STIG lessons per
operating system and version. Each supported system has its own playbook
folder, content folder and Semaphore tab:

| System | Playbooks in the lab folder | SCAP files you supply | Semaphore tab |
| --- | --- | --- | --- |
| RHEL 9 | `playbooks/stig/rhel/9/` | `content/rhel/9/` | **STIG · RHEL 9** |
| AlmaLinux 9 | `playbooks/stig/almalinux/9/` | `content/almalinux/9/` | **STIG · AlmaLinux 9** |
| Rocky Linux 9 | `playbooks/stig/rocky/9/` | `content/rocky/9/` | **STIG · Rocky Linux 9** |
| Ubuntu 24.04 | `playbooks/stig/ubuntu/24.04/` | `content/ubuntu/24.04/` | **STIG · Ubuntu 24.04** |

Each playbook folder holds `audit.yml` and `apply.yml`. They are short
wrappers that name their system and run the shared `playbooks/stig/audit.yml`
and `playbooks/stig/apply.yml`, so a fix to the shared playbooks reaches every
system. Semaphore tabs cannot be nested, so each system and version gets one
flat tab. Ansible tells the systems apart by the facts it gathers, the
distribution and its major version, or the full version on Ubuntu; your
inventory groups stay `ubuntu` and `enterprise_linux`, and one host can only
match one system.

Every tab holds three templates, named after its system, for example
**RHEL 9 · STIG audit**. The RHEL 9 and Ubuntu 24.04 tabs add a fourth for
DISA's own benchmark, because DISA publishes SCAP content for those two
systems only. The templates wrap the operating-system vendor's own STIG tooling
and content that this chapter walks through by hand: the packaged SCAP Security
Guide `stig` profile on RHEL, AlmaLinux and Rocky Linux, and the Ubuntu
Security Guide `disa_stig` profile on Ubuntu.
The guide adds no rules of its own. On Enterprise Linux two things differ from
the hand-run commands above. First, the scans omit
`--fetch-remote-resources`, so a rule whose check lives in a remote vendor
feed, such as `security_patches_up_to_date`, reports `notchecked`. To fetch
those feeds, set `stig_fetch_remote_resources` to `true` in a variable group,
or pass `-e '{"stig_fetch_remote_resources": true}'` from the CLI; the target
then needs access to them. Second, the remediation is
`oscap xccdf eval --remediate` with the data stream's own fixes, not the
packaged Ansible playbook applied on RHEL above.

- **STIG audit** runs on the system's inventory group, `enterprise_linux` or
  `ubuntu`, and skips the hosts there that run another system; the log names
  each skipped host and its system. On the hosts it keeps, it installs the
  scanner where missing, runs the assessment, keeps the XML and HTML on the
  target under `/var/log/stig-scans/STAMP/`, fetches them to the
  controller under `stig-reports/<system>/<version>/STAMP/HOST/` in the home of
  the account that runs the playbook, for example
  `/var/lib/semaphore/stig-reports/rhel/9/` for a Semaphore run and
  `~/stig-reports/rhel/9/` for your own CLI run, and prints outcome counts.
  `STAMP` is the controller's UTC time when the run started, such as
  `20261019T061020Z`; every host of one run shares it, and so do an apply's
  before and after reports. If no host in the group runs that system, the run
  stops and says which systems the hosts run. It changes no policy. Ubuntu needs `usg` already
  installed through your own Ubuntu Pro attachment. Without it, that host fails
  with an explanation while the other hosts' scans still complete.
- **STIG apply (approval required)** scans, applies the vendor remediation with
  `oscap --remediate` or `usg fix`, and scans again; **STIG apply, allow
  required reboot** also reboots before the second scan. Each changes exactly
  one target per run: its Run dialog asks for that host in **Limit**, for
  example `lab-alma` on the AlmaLinux 9 tab, and for confirmation that a
  recovery point for it exists. A run selecting more than one host is refused
  before any connection, and a host that runs another system is refused before
  anything changes, with the name of the template to use instead. When that
  one target is the controller the run comes from, the fixes are applied and
  the reboot is left alone, because it would stop the run before the second
  scan; the last message says so. Restart the controller from its own
  terminal with `sudo systemctl reboot` when no task is running, then run the
  audit. On an Ubuntu controller the fixes also run without `needrestart`,
  which would restart Semaphore after a library update and end the run
  halfway; the restart of the controller covers those services. From the CLI
  the same gates are `--limit lab-alma` and `-e '{"stig_confirm": true}'`, plus
  `--ask-vault-pass` if you chose the Vault option for sudo passwords.
- **STIG audit, DISA SCAP file** (RHEL 9 and Ubuntu 24.04) scans with DISA's
  benchmark file, which you place in the system's `content/` folder, using the
  profile in the **DISA SCAP file ·** variable group of that system; see
  [scan with a local SCAP content file](#scan-with-a-local-scap-content-file).

From the CLI, run the playbook of the system you mean, for example
`ansible-playbook playbooks/stig/rhel/9/audit.yml --limit enterprise_linux -K`.
`-K` sends the one password you type to every host that the run uses sudo on,
so when your targets have different sudo passwords, limit the run to one host,
such as `--limit lab-rhel`, or use the Vault option, which gives each host its
own. Hosts of another system are skipped or refused before Ansible uses sudo
on them, so their passwords are never tried.
The shared `playbooks/stig/audit.yml` still audits every supported system in
its limit at once, with reports under `~/stig-reports/STAMP/`, and
`playbooks/stig/apply.yml` applies to whichever single host you name.

The STIG templates refuse Dry Run because the scanner does not run in check
mode.

**Check:** after an audit, the task log shows for each host a JSON summary of
pass, fail, not-applicable and not-checked counts, with the selected totals.
Three lines follow it: the STIG release and content the scan measured, with
any exceptions file; the failing rules by DISA category, with the STIG IDs of
the failing CAT I rules and the path of the findings file; and where its
reports are:
on the target, and under the controller home of the service or of your
account, depending on where you ran it. The findings file,
`audit-findings.csv` beside `audit.xml`, lists every failing, unchecked or
errored rule with its category, STIG ID and rule ID. Only the `semaphore` account and root
can read the service's home; copy a Semaphore run's reports to your own account
to open them, with the stamp folder the log names:

```bash
sudo cp -r /var/lib/semaphore/stig-reports/rhel/9/STAMP ~/
sudo chown -R "$USER": ~/STAMP
```

If the summary shows
`has_scanner_errors_or_unknowns: true`, a warning follows it. Treat that scan
as incomplete and see
[chapter 11](11-troubleshooting.md#benchmark-result-surprises) before
comparing counts.

**Concept:** vendor remediation is not gentle. It commonly removes
passwordless sudo, tightens SSH and changes kernel parameters, and a first
pass often leaves failing rules that need a reboot or a manual decision. On
AlmaLinux, Rocky Linux and RHEL 9 it sets the `FIPS:STIG` crypto policy. In the
verification run an AlmaLinux target then offered only RSA and ECDSA host keys
and refused Ed25519 user keys, including an administrator's everyday Ed25519
key; expect the same on RHEL 9 and Rocky Linux, which apply the same policy,
although the run did not check their host-key offer. The guide's RSA host-key pin and RSA 4096
automation key keep working. The policy alone does not enable FIPS mode; see
the interpretation section above before treating a host as FIPS. Run it
only against a disposable target with console access and a recovery point.

## Leave out rules you have an accepted exception for

Some rules cannot or should not be met on a given system: a separate `/tmp`
file system on a VM built without one, a boot loader password on a VM nobody
boots by hand, FIPS mode under an application that does not support it. An
audit then fails those rules on every run, and **STIG apply** tries to fix them
on every run. SCAP has a standard record for such decisions, an XCCDF
*tailoring file*: it defines a profile that extends the published one and
unselects the rules you name. The published content stays as it is, and the
file is the record of what was left out.

The STIG playbooks call it the exceptions file and take it in two ways:

- **By its place.** A per-system playbook uses `tailoring.xml` in its system's
  content folder when that file exists: `content/rhel/9/tailoring.xml` for the
  templates of **STIG · RHEL 9**, and likewise for the other systems. The file
  is for the vendor's content, so the **DISA SCAP file** template does not use
  it.
- **By name.** `stig_tailoring_file`, a path in the lab folder or an absolute
  one, in a variable group or with `-e`. A named file is used by every STIG
  run, the DISA file scan included, and takes the place of the folder's file.

With an exceptions file:

- the audit and both scans of an apply use the file's profile, so the rules it
  leaves out report `notselected` instead of `fail`;
- **STIG apply** does not fix them;
- every run prints the file's name, its SHA-256, the profile it extends, the
  rules it leaves out and how many values it sets, and the release line ends
  with
  `with exceptions file tailoring.xml, which leaves out 2 rule(s) or group(s)`
  instead of `no exceptions file`.

The file is refused before anything is scanned or changed when it is not an
XCCDF tailoring file with exactly one profile, or when that profile extends
another profile than the one the run scans with. An exceptions file therefore
cannot replace the STIG with another baseline. On Ubuntu, `usg` takes the
profile from the file instead of a name, so the file must extend the STIG
profile, and it is refused when `stig_usg_profile` names anything but that
profile: `disa_stig`, the default, `stig` or `stig-v1r1`. A file can also
change a rule without leaving it out, with a `refine-rule` that gives it
another role, severity or weight; the run names those rules as refined. A
file in the folder is as
strong as an option in a template: keep the lab folder writable only by the
people who may accept an exception, and commit the file so that its history
shows who changed it.

**Where: one target of the system, as its administrator.** Make the file with
the vendor's own tool on a machine that has the content. The rule IDs to leave
out are in the `rule_id` column of `audit-findings.csv`.

On RHEL, AlmaLinux and Rocky Linux, `autotailor` from `openscap-utils` writes
the file from the data stream, the profile it extends, and the rules to
unselect. Use the data stream of the system: `ssg-rhel9-ds.xml`,
`ssg-almalinux9-ds.xml` or `ssg-rl9-ds.xml`.

```bash
sudo dnf install -y openscap-utils
autotailor --output tailoring.xml \
  --new-profile-id xccdf_org.ssgproject.content_profile_stig_site \
  --unselect xccdf_org.ssgproject.content_rule_partition_for_tmp \
  --unselect xccdf_org.ssgproject.content_rule_grub2_password \
  /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml xccdf_org.ssgproject.content_profile_stig
```

On Ubuntu 24.04, `usg` writes a file that lists every rule of the profile, each
under a comment with its STIG ID, and the values the profile sets. `usg` runs
as root and the file is root's, so hand it to your account; then change
`selected="true"` to `selected="false"` on each rule to leave out, here the
session-lock package:

```bash
sudo usg generate-tailoring disa_stig tailoring.xml
sudo chown "$USER": tailoring.xml
sed -i '/content_rule_vlock_installed"/s/selected="true"/selected="false"/' tailoring.xml
grep 'selected="false"' tailoring.xml
```

The last command prints one line for each rule the file leaves out.

**Where: the controller, as the lab folder's editor.** Bring the file to your
home folder on the controller, for example with
`scp ADMIN@ADDRESS:tailoring.xml ~/`. Copy it to the system's content folder,
readable by the `semaphore` group like DISA's benchmark, and check what the
playbooks will read from it:

```bash
cd /opt/ansible-lab
install -m 0640 ~/tailoring.xml content/rhel/9/tailoring.xml
python3 scripts/summarize_xccdf.py --tailoring content/rhel/9/tailoring.xml
```

**Check:** the output names `profile_id`, the profile it `extends`, and under
`left_out` exactly the rules you chose. `values_set` counts the values the
file sets: none in a file from `autotailor` that only unselects rules, and
every value of the profile in a file from `usg`, changed or not. Run
**RHEL 9 · STIG audit**: the log names the exceptions file and its SHA-256
before the scan, and the summary's `notselected` count is higher by the rules
left out. In the test it rose from 1063 to 1065 on RHEL 9.8 and from 409 to
411 on Ubuntu 24.04, with two rules left out on each. To stop using the file,
remove it from the folder.

**Concept:** an exception is a decision someone owns, not a way to a shorter
list. Record for each rule who accepted it, why, and until when; the file
holds only the rule. A rule left out is not assessed at all, so review the
file whenever the content's release changes, and scan without it from time to
time to see what it hides.

## Scan with a local SCAP content file

The audit can also scan with a SCAP data stream file you supply instead of
the vendor's packaged content, for example DISA's own SCAP benchmark for a
newer STIG release. The file lives in the lab folder, so no repository or
download happens during the run. `stig/audit.yml` then uses OpenSCAP on
either family, installing `openscap-scanner` where it is missing, and the
results, summary and HTML report work as for the vendor scan.

**Where: the controller, as the lab folder's editor.** DISA publishes each
SCAP benchmark as a ZIP file that downloads without an account. Check the
[DISA SCAP content page](https://public.cyber.mil/stigs/scap/) for the current
release; the example uses the RHEL 9 benchmark V2R10, which DISA posted on
5 October 2026:

```bash
cd /opt/ansible-lab/content/rhel/9
curl -fLO https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.zip
sha256sum U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.zip
python3 -m zipfile -e U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.zip .
chmod 0640 U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml
grep -o 'Profile id="[^"]*"' U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml
```

Record the checksum with your results. The seeded installers create
`content/` in the lab folder with one folder per system and version, and the
example works in `content/rhel/9/`, where the seeded RHEL 9 variable group
expects the file; for Ubuntu 24.04 use `content/ubuntu/24.04/` and the Ubuntu
benchmark from [the catalog](appendices/security-baselines.md). The file must
stay readable by the `semaphore` group, which `chmod 0640` keeps. DISA benchmarks list the profiles
`xccdf_mil.disa.stig_profile_MAC-1_Classified` through `MAC-3_Sensitive`,
plus `CAT_I_Only` and `Disable_Slow_Rules`. Choose the one your system owner
names; `MAC-1_Classified` selects the most checks.

**In Semaphore:** the variable group **DISA SCAP file · RHEL 9** already holds
the system's content folder and the profile of this example:

```json
{
  "stig_content_file": "content/rhel/9",
  "stig_content_profile": "xccdf_mil.disa.stig_profile_MAC-1_Classified"
}
```

`stig_content_file` may name a file or a folder. A folder stands for the one
file in it whose name ends in `_Benchmark.xml`, as DISA names its benchmarks,
so a newer DISA release needs no edit: replace the file in the folder. The
run's release line then shows which one it scanned with, for example
`STIG release V2R10 (Benchmark Date: 30 Sep 2026)`, and
`copied from U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml`. While the folder
holds no benchmark, or more than one, the run stops before scanning and says
which. A controller updated from an earlier release keeps the value its group
had, the path of the V2R9 file; that still works, and you can change it to the
folder.

Run **RHEL 9 · STIG audit, DISA SCAP file** from the **STIG · RHEL 9** tab. It
scans the RHEL 9 hosts in `enterprise_linux` and skips AlmaLinux and Rocky
Linux hosts, which the benchmark does not cover. For a profile your system
owner names, edit that value in the variable group;
**DISA SCAP file · Ubuntu 24.04** works the same way for
`content/ubuntu/24.04/`. From the CLI, run from the lab folder with your own
key and the targets' sudo password, as [chapter 5](05-cli-lessons.md) does,
and pass the same two variables:

```bash
cd /opt/ansible-lab
/opt/ansible-venv/bin/ansible-playbook playbooks/stig/rhel/9/audit.yml --limit lab-rhel \
  --private-key ~/.ssh/ansible_lab -K \
  -e '{"stig_content_file": "content/rhel/9", "stig_content_profile": "xccdf_mil.disa.stig_profile_MAC-1_Classified"}'
```

On a seeded controller that key must be authorized on the targets beside the
service key; [Stage 4](stage-4-add-target-first-job.md#do-add-the-target-with-add-targetsh)
shows how. With the Vault option for sudo passwords, use `--ask-vault-pass`
instead of `-K`.

A relative path is read from the lab folder; an absolute path works too. The
content is for audits only: `stig/apply.yml` refuses `stig_content_file`,
because DISA benchmarks carry checks but no fixes, and remediation always
uses the vendor's packaged content.

A benchmark checks that it runs on its own platform. In the test, DISA's RHEL 9
benchmark reported all 392 of its rules as not applicable on AlmaLinux 9.8,
which is why the DISA template of each system scans only that system's hosts;
scan AlmaLinux and Rocky Linux with their own packaged content. DISA content
and the vendor's `stig` profile also check different releases in different
ways, so their counts differ on the same machine. On targets the vendor STIG
had already hardened, the tests of September and November 2026 saw:

| Target | Content and profile | Pass | Fail | Not applicable |
| --- | --- | --- | --- | --- |
| RHEL 9.8 | DISA RHEL 9 V2R9, `MAC-1_Classified` | 340 | 27 | 25 |
| RHEL 9.8 | DISA RHEL 9 V2R10, `MAC-1_Classified` | 345 | 22 | 25 |
| AlmaLinux 9.8 | DISA RHEL 9 V2R9, `MAC-1_Classified` | 0 | 0 | 392 |
| Ubuntu 24.04 (Ubuntu Pro) | DISA Ubuntu 24.04 V1R5, `MAC-1_Classified` | 141 | 22 | 2 |
| Ubuntu 24.04 (Ubuntu Pro) | DISA Ubuntu 24.04 V1R6, `MAC-1_Classified` | 142 | 24 | 2 |

The November machines had four and two rules left unfixed by an exceptions
file. The V2R9 and V1R5 runs reported zero scanner errors. In the V2R10 run one
rule, `RHEL-09-653030`, ended `unknown` before and after the fixes, so the log
carried the warning that the scan is incomplete; read such a rule in the HTML
report. Before any fix, the same two machines failed 220 of V2R10's 393 rules
and 120 of V1R6's 168. The Ubuntu benchmark took almost nine minutes for each
scan on a VM with two processor cores, and the RHEL one 20 seconds. The same
variables select other
content, such as a newer SCAP Security Guide release's data stream or a CIS
profile's; [the security baseline catalog](appendices/security-baselines.md)
lists the profile IDs by platform.

## Harden the controller itself

The controller holds the automation key and the sudo password of every
target, so where the STIG applies, it applies to the controller first. This
section was run on a RHEL 9.8 controller with the vendor's `stig` profile, also
in FIPS mode, in November 2026
([record](validation/2026-11-hardened-controller.md)). The orders, the table
and the four rules below are for Enterprise Linux;
[an Ubuntu controller](#an-ubuntu-controller) has its own short list.

Both orders work:

- **Install first, harden later.** Run **RHEL 9 · STIG apply** with the
  controller's own inventory name in **Limit**. The fixes are applied and the
  reboot is left to you, as [the templates](#the-seeded-stig-templates)
  describe; restart it from its own terminal. Semaphore and its jobs keep
  running afterwards. Your own work as the administrator needs the two steps
  below.
- **Harden first, install later,** as on a hardened image. Clone the guide
  with `git clone --template=` and the address of Stage 1: on a hardened
  system Git may not copy one of its own sample hooks, and a plain
  `git clone` ends with `cannot copy ... fsmonitor-watchman.sample:
  Operation not permitted`. `git init` fails the same way and takes the same
  option, as for chapter 7's `git init --bare`. The installer then stops
  before it changes anything and prints the four rules below with your
  paths. Add them, load them and run the installer again. Until they are
  loaded your own account may not open the guide's Python files; read them
  with `sudo less`.

What the STIG sets, and what it means for this guide:

| The STIG sets | What you notice on the controller | What to do |
| --- | --- | --- |
| `fapolicyd`, which lets every account but root open and run only scripts and programs that a package installed | As the administrator, `git status` in the guide's folder or the lab folder lists scripts as modified, `git checkout` and `git pull` refuse, `update-controller.sh` reports a problem and changes nothing, and `python3 scripts/summarize_xccdf.py` and `/opt/ansible-venv/bin/ansible` end with `Operation not permitted`. Jobs in Semaphore keep running. | Add the four rules. |
| `umask 077` for every login | A playbook you create in the lab folder is `-rw-------`, and its template fails with `Permission denied`. The guide's own tools set the modes of what they write. | Make the file readable by its group, or give the lab folder a default ACL once. |
| A sudo password at every command, and no `NOPASSWD` rule | The guide's tools ask more often. | Nothing. |
| The `FIPS:STIG` crypto policy | Ed25519 keys are refused; the guide's RSA keys work, as [above](#the-seeded-stig-templates). | Nothing. |
| Nothing for FIPS mode itself: the fixes leave `sudo fips-mode-setup --enable` and the restart to you | With it on, Semaphore, PostgreSQL, the HTTPS proxy, jobs and the update tools kept working. `ssh-keygen` no longer reads an Ed25519 key, so the one-command onboarding leaves that host key out of its list and says so. | Nothing. |
| A shell that closes after ten idle minutes, and a login banner | An idle terminal ends. | Nothing. |

**Where: the controller, as its administrator.** The four `fapolicyd` rules
name Semaphore's binary, the Ansible runtime, the lab folder and the guide's
folder. The file's number matters: the runtime holds shared libraries, so its
rule has to come before `fapolicyd`'s own rules for those, which start at 40.

```bash
guide=$(realpath ~/ansible-semaphore-guide)
sudo install -o root -g fapolicyd -m 0644 /dev/stdin /etc/fapolicyd/rules.d/35-ansible-semaphore-guide.rules <<RULES
allow perm=any all : path=/usr/local/bin/semaphore
allow perm=any all : dir=/opt/ansible-venv/
allow perm=open all : dir=/opt/ansible-lab/ ftype=%languages
allow perm=open all : dir=$guide/ ftype=%languages
RULES
sudo fagenrules --load
```

`fapolicyd` compares the path that a symbolic link leads to, which is why
`realpath` names the guide's folder; write a lab folder elsewhere than
`/opt/ansible-lab` the same way. A rule cannot name a path with a space in it
as these lines are written, and the installer refuses such a folder.

`fapolicyd` takes a few seconds to load them. The first two lines allow what
the installer put there, which no package owns; only root can write to either
path. The last two let you and Git read the scripts in the two folders, which
also lets an interpreter run them; only you can write there. A rule allows
whatever is at its path, so keep those owners as they are. `fapolicyd`'s trust
files, with `fapolicyd-cli --file add`, are the other standard way and worked
in the run for the first two paths on an installed controller; they cannot be
written before the files exist, so they do not help the installer. The
installer looks for the four lines as they are written here, each before
`fapolicyd`'s own rule that would deny it, and then reads one of the guide's
scripts as your account to see that `fapolicyd` has loaded them. Where your
site allowed the same paths another way, `--fapolicyd-ready` skips that check.
Either way this is a change to the system's allowlist: record it and have it
approved like any other exception.

**Why jobs kept running without the rules.** The Semaphore service runs in its
own mount namespace, and RHEL 9's `fapolicyd` does not watch other namespaces
unless `allow_filesystem_mark = 1` is set in `/etc/fapolicyd/fapolicyd.conf`.
The STIG profile leaves it at 0. With 1 and without the rules, Semaphore did
not start: `Failed to execute /usr/local/bin/semaphore: Operation not
permitted`. With the rules it started, and Ping, Baseline preview, the health
report and the STIG audits passed; the audits needed this release's
`ansible.cfg`, which sends the modules of tasks that run on the controller
through a pipe as well. Add the rules even where jobs work without them. They
cover this guide's project, which Semaphore reads from the lab folder. A
project that Semaphore clones from a Git server is copied under
`/var/lib/semaphore/tmp/`, which none of the four lines names; that case was
not run.

**Your own files under `umask 077`.** Make a new playbook readable by the
`semaphore` group, or set a default ACL once, after which new files in the lab
folder are created `-rw-r-----` whatever the umask:

```bash
chmod g+r /opt/ansible-lab/playbooks/my-playbook.yml
setfacl -R -d -m g::rX /opt/ansible-lab
```

**Check:** `git status --short` prints nothing in both folders,
`sudo python3.12 controller/check-controller.py` passes, and **Ping** and
**RHEL 9 · STIG audit** succeed. On the controller hardened after its
installation the audit left 13 failing rules, among them the boot loader's
password and administrator name and FIPS mode in CAT I, which are yours to
decide. A controller installed on a hardened machine failed one more,
`RHEL-09-411035`: PostgreSQL's package gives its `postgres` account a login
shell. Where the vendor's fixes followed the installation, that rule did not
fail and the controller ran. With FIPS mode enabled as well, the FIPS rule
passed and two remained in CAT I, the boot loader's password and
administrator name.

**The browser.** On the hardened controller, with FIPS mode on as well and in
both orders, Semaphore's UI was walked with Chromium through the tunnel of
[Stage 1](stage-1-controller.md#do-open-semaphore) and, published with
`--expose https`, by the controller's address: the sign-in, the eight tabs, a
template started from its form, its live log, the inventory, key and
repository pages, and the sign-out. `firewalld` kept the `https` service that
the installer added, and the proxy answered TLS 1.2 and 1.3 only.

### An Ubuntu controller

An Ubuntu 24.04 controller was hardened with **Ubuntu 24.04 · STIG apply**,
its own name in **Limit**, restarted, and walked in the browser the same way.
Ubuntu's profile has no `fapolicyd`, so none of the four rules applies there,
and a file you create in the lab folder stays readable for Semaphore. Three
other things matter:

- **`needrestart`.** After a package change that updates a library, Ubuntu
  restarts the services that use it, and Semaphore, which runs the job, is one
  of them. The first apply ended halfway that way. The **STIG apply** and
  **Patch** playbooks now suspend `needrestart` where the target is the
  controller the run comes from; the controller's restart, or
  `sudo needrestart` from its terminal, covers the services afterwards.
- **The SSH client's files.** `usg` works with `umask 077`, so its fix for the
  SSH client's ciphers and MACs leaves `00-cipher-list.conf` and
  `00-mac-list.conf` in `/etc/ssh/ssh_config.d` for root only. `ssh` then ends
  with `Can't open user config file ...: Permission denied` for every other
  account, and on a controller every job fails as unreachable. On its own
  controller the apply playbook gives those files mode `0644` back in the same
  command. On a machine you hardened with `sudo usg fix disa_stig` yourself,
  and on a target whose accounts use `ssh`, do it by hand; the audit counted
  no finding for it:

  ```bash
  sudo chmod 0644 /etc/ssh/ssh_config.d/*.conf
  ```

  On such a machine the installer stops before it changes anything and
  prints that command, and on an installed controller the readiness check
  reports `"service_can_start_ssh": false`.

- **The login banner.** An interactive login asks `Do you agree? [y/N]` before
  the shell. Jobs and the guide's own tools are not asked.

## Concept

The deliverable is a reproducible configuration with evidence and understood
exceptions. A completed automation task, an enabled FIPS flag and a benchmark
certificate are different claims and require different evidence.
