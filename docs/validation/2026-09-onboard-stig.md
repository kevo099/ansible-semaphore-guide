# Validation record: onboarding and STIG on Azure, September 2026

[Back to validation and limits](../VALIDATION.md) · [Azure chapter](../13-azure.md) · [Chapter 9](../09-security-benchmarks.md)

On 28 September 2026 the onboarding files, the vendor STIG lessons, both seeded
controllers and the local SCAP content audit were run on Azure in a disposable
resource group, which was then deleted.

## How it ran

- **Subscription and region:** the same sponsored subscription and `eastus2`
  as the [first Azure record](2026-09-azure.md); every VM `Standard_D2als_v6`.
- **Keys:** RSA 4096 for the Azure administrator and for the automation account,
  so they keep working under the Enterprise Linux `FIPS:STIG` crypto policy.
- **Targets:**
  - `lab-ubuntu`: Ubuntu 24.04, **Ubuntu Pro** image, made by `targets.yml` with
    [`examples/onboard/cloud-init.yaml`](../../examples/onboard/cloud-init.yaml).
  - `lab-alma`: AlmaLinux 9.8, made by `targets.yml` with the same file.
  - `lab-rhel`: RHEL 9.8 pay-as-you-go and `lab-ubuntu2`: plain Ubuntu 24.04,
    both made with `az vm create` and no custom data, to stand in for existing VMs.
  - Three short-lived VMs (Ubuntu 24.04 and AlmaLinux 9.8 with the key pasted into
    the file by hand, and Ubuntu 24.04 with the placeholder left in) tested the
    portal path of the cloud-init file.
- **Controllers:** the Azure Ubuntu 24.04 controller, first used only as the SSH
  jump host for runs from a workstation and then installed with the seeded Ubuntu
  installer; and an AlmaLinux 9.8 VM in the same subnet, installed with the
  Enterprise Linux installer. Both ran this branch's code.
- **Secrets:** sudo passwords were generated for the run and reached the VMs only
  as SHA-512 hashes; no password or hash appears in these records.

## Results: onboarding

| Step | Result |
| --- | --- |
| Run Command execution model | Azure runs the script as root with `/bin/sh -c PATH`, which is dash on Ubuntu; the script's `#!/bin/bash` line applies, and it re-runs itself with bash otherwise. Azure sends the script in encrypted protected settings; the VM agent keeps a root-only copy per run. |
| `onboard-linux.sh`, unchanged placeholder | `RESULT: FAILED` asking for the key; nothing changed. |
| `onboard-linux.sh` on `lab-rhel` (no `svc_ansible`) | Created the account, keys, password from a pasted hash, sudoers rule and SSH drop-in; `RESULT: OK`. A repeat run reported every part unchanged. |
| `onboard-linux.sh` on `lab-ubuntu2` | Key only: `password: NOT SET`. Then as a managed Run Command with the unedited file, the key as a parameter and the hash as a protected parameter: `password: set from PASSWORD_HASH`. Reading the command back showed the key parameter and no protected value. |
| `onboard-linux.sh` completing the cloud-init targets | Set the password; every other part was already in place. |
| Self-removal of a pasted hash | The run's copy under `/var/lib/waagent/run-command/download/` was gone after a run with a pasted hash; earlier runs' copies remained. |
| Refusals, each with nothing changed where it matters | A key comment holding quotes and `$(touch ...)` was stored as text and nothing ran; `rounds=0` in the hash; an Ed25519-only key on a `FIPS:STIG` host; a `Match User ... Address` block that re-enabled passwords for the controller's address (the drop-in was left as it was and SSH was not reloaded); a command-specific `NOPASSWD` rule for the account. |
| Host keys | The fingerprints the script printed matched `ssh-keyscan` from the controller on all four targets, and `add-target.sh` accepted them. |
| `cloud-init.yaml` through `targets.yml` | Ubuntu Pro and AlmaLinux: `status: done`, drop-in effective (`authenticationmethods publickey`). |
| `cloud-init.yaml` pasted by hand | Ubuntu and AlmaLinux: `svc_ansible is ready`. Placeholder left in: `status: error`, the missing-key message, and no authorized key. |
| `bootstrap-existing-vm.yml` with the tightened checks | Passed on `lab-ubuntu2` as the Azure administrator. |

## Results: vendor STIG on Azure

`stig-audit.yml` and then `stig-apply.yml` with `allow_reboot`, one target per
run, from a workstation through the controller:

| Target | Failing rules before → after | Passing before → after | Not applicable before → after |
| --- | --- | --- | --- |
| Ubuntu 24.04, Ubuntu Pro, usg 24.04.8 `disa_stig` | 67 → 8 | 54 → 209 | 105 → 8 |
| AlmaLinux 9.8, `stig` | 268 → 22 | 155 → 406 | 44 → 39 |
| RHEL 9.8 pay-as-you-go, `stig` | 262 → 15 | 170 → 420 | 35 → 32 |

- Every scan reported zero scanner errors. Each apply took about eight minutes
  including the reboot, and Ansible reconnected.
- On plain Ubuntu 24.04 the audit stopped for that host with the Ubuntu Pro
  explanation. On the Ubuntu Pro image, Pro was attached already and
  `pro enable usg` made `usg` available; `usg list` showed CIS v1.0.0 profiles
  and `stig-v1r1`.
- Afterwards the Azure VM agent reported `Ready` and Run Command worked on all
  three. `svc_ansible` logged in with its RSA key and sudo required and accepted
  its password. The administrator's cloud-init `NOPASSWD` rule was commented
  out, so the administrator had no sudo. Enterprise Linux used `FIPS:STIG` with
  `fips_enabled` 0 and gave `svc_ansible` a 60-day password lifetime; Ubuntu did
  not change it.
- Ping, Baseline and Webserver applied on all three hardened targets and
  repeated with `changed=0`. The onboarding script repeated with every part
  unchanged on all three.
- A second remediation pass on RHEL, run from Semaphore, went from 16 failing
  rules to 13.

## Results: seeded controllers and local content

| Step | Result |
| --- | --- |
| Ubuntu installer, seeded | Installed and seeded in 58 seconds on the Azure controller; all 13 readiness checks passed; project, local lab folder repository and eleven templates, before the local content template was added. |
| Enterprise Linux installer, seeded | Installed and seeded in 56 seconds on AlmaLinux 9.8 with the shared installer code; all 13 readiness checks passed; twelve templates. |
| `add-target.sh` | Added four targets on the Ubuntu controller and three on the Enterprise Linux one, each with the fingerprint Run Command had printed. |
| Ubuntu controller, through the API | Ping succeeded on four targets; the STIG audit completed on three and stopped on the plain Ubuntu target as designed; Baseline preview succeeded; STIG apply with the approved reboot on `lab-rhel` succeeded. No run cloned anything; paths were under the lab folder. |
| Local content template, placeholders | Stopped before scanning with the explanation. |
| DISA RHEL 9 V2R9 `MAC-1_Classified` | RHEL 9.8: 340 pass, 27 fail, 25 not applicable. AlmaLinux 9.8: all 392 not applicable. |
| DISA Ubuntu 24.04 V1R5 `MAC-1_Classified` | Ubuntu Pro target: 141 pass, 22 fail, 2 not applicable. |

## Found and fixed during the run

- **Ubuntu SSH check before the first connection.** Ubuntu 24.04 starts
  `ssh.service` from its socket on the first connection, and until then
  `sshd -t` fails for lack of `/run/sshd`. Both the script and the cloud-init
  file failed safely (they removed the drop-in and did not reload) and now create
  that runtime directory first. The Ansible playbook never met this because it
  connects over SSH.
- **Password state on Enterprise Linux.** `passwd -S` printed nothing through
  Run Command on AlmaLinux; the script now reads the shadow entry.
- **Managed Run Command parameters.** The Azure CLI takes `NAME=value`; the form
  `name=X value=Y` silently created two parameters with those literal names.

## Review and retest

An adversarial review of the onboarding files found seventeen problems. All
were fixed and retested above:

- a key comment could break out of the shell string and run code as root;
- root wrote into the account's own `.ssh` directory, where a planted link
  could redirect the write;
- the sudo check missed command-specific `NOPASSWD` rules and `rootpw`-style
  defaults (also fixed in `bootstrap-existing-vm.yml`);
- the SSH check used only the loopback address and did not require
  `pubkeyauthentication yes` or the expected authorized-keys file (also fixed
  in the playbook);
- a failed reload could look like success on a later run;
- a malformed `rounds=` value would have been installed as an unusable password;
- file ownership and mode were not enforced when the content already matched;
- an Ed25519-only key could lock the account out on a hardened host;
- the cloud-init run reported success after failures and did not notice a
  missing key;
- the Azure administrator could not safely be named `svc_ansible`;
- and smaller issues with the order of checks, key comments in YAML and
  output length.

## Not established

- Rocky Linux on Azure, ARM64 sizes, Trusted Launch or confidential VMs, and
  other regions.
- FIPS mode, Ubuntu FIPS kernels, and STIG applied to the controllers.
- Several keys passed as one managed Run Command parameter; the test passed one.
- The per-target Vault option for sudo passwords on a seeded controller; the
  test used one shared sudo credential on the inventory.
- A comparison with DISA's SCAP Compliance Checker on the same targets.
