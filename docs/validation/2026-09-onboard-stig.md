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
| `bootstrap-existing-vm.yml` with the tightened checks | Passed on `lab-ubuntu2` as the Azure administrator. With an RSA-only server policy and an Ed25519-only key list, it stopped before replacing any key. |
| After the final review, `onboard-linux.sh` | Stopped and asked for `CONTROLLER_ADDRESS` when a `Match ... Address` rule existed and none was given; refused a 1024-bit RSA key and an Ed25519 key under an RSA-only policy; with the same keys, reset a `.ssh` of mode 0777 and a key file of 0666 to 0700 and 0600. |
| After the final review, the cloud-init checks | Run as root on existing VMs: a wrong `AuthorizedKeysFile` and `Defaults rootpw` each ended in an error; with `ssh.service` and `ssh.socket` stopped on Ubuntu, and `sshd` stopped on RHEL, it started SSH and finished. Two fresh VMs, Ubuntu 24.04 and AlmaLinux 9.8, then reported `svc_ansible is ready`. |
| Managed Run Command with two keys | The unedited script, with both keys in one parameter, the controller address as a parameter and the hash protected, reported every part unchanged. |
| Final cloud-init file on fresh VMs | Ubuntu 24.04 and AlmaLinux 9.8 created with the final file reported `status: done` and `svc_ansible is ready`. |

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
| Ubuntu installer, seeded | Installed and seeded in 58 seconds on the Azure controller; all 12 readiness checks passed; project, local lab folder repository and eleven templates, before the local content template was added. |
| Enterprise Linux installer, seeded | Installed and seeded in 56 seconds on AlmaLinux 9.8 with the shared installer code; all 12 readiness checks passed; twelve templates. |
| `add-target.sh` | Added four targets on the Ubuntu controller and three on the Enterprise Linux one, each with the fingerprint Run Command had printed. |
| Ubuntu controller, through the API | Ping succeeded on four targets; the STIG audit completed on three and stopped on the plain Ubuntu target as designed; Baseline preview succeeded; STIG apply with the approved reboot on `lab-rhel` succeeded. No run cloned anything; paths were under the lab folder. |
| Local content template, placeholders | Stopped before scanning with the explanation. |
| DISA RHEL 9 V2R9 `MAC-1_Classified` | RHEL 9.8: 340 pass, 27 fail, 25 not applicable. AlmaLinux 9.8: all 392 not applicable. |
| DISA Ubuntu 24.04 V1R5 `MAC-1_Classified` | Ubuntu Pro target: 141 pass, 22 fail, 2 not applicable. |
| `remove.yml` | With VMs made by the Azure CLI still present, it removed its own VMs and stopped at `InUseNetworkSecurityGroupCannotBeDeleted`. After those were deleted, it removed the network and kept the group because the three snapshots remained. After the snapshots were deleted, it deleted the group. |

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

Three adversarial reviews examined the onboarding files. The first found
seventeen problems. The second, run on the branch before publishing, found
that four of those were only partly fixed and raised eight more. A third pass
verified those fixes: nine held, three were still partial, and two fixes had
introduced new bugs (the playbook refused RSA keys on a server that allows only
`rsa-sha2-256`, and an absolute `AuthorizedKeysFile` was rejected). Those five
were then fixed and retested live. The table gives each problem's final fix
and the retest behind it.

| Problem | Fix | Retest |
| --- | --- | --- |
| A key comment could break out of the shell string and run code as root | Keys are read through a quoted here-document | Live: a comment with quotes and `$(touch ...)` was stored as text; nothing ran |
| Root wrote into the account's own `.ssh`, where a planted link could redirect it | The account writes its own key file | Offline review; live runs wrote the file as `svc_ansible` |
| Only `sudo -n true` was tested, missing command-specific `NOPASSWD` rules and `rootpw`-style defaults | The full `sudo -l` listing is checked, in the script, the playbook and cloud-init | Live: a command-specific `NOPASSWD` rule and `Defaults rootpw` were refused |
| The SSH check used loopback, which can differ from the controller's address | `CONTROLLER_ADDRESS`, checked for each of the VM's addresses and SSH ports; without it, a `Match` rule on the client's address, found by following every `Include`, stops the script and makes cloud-init report an error; the playbook uses its own connection's addresses and ports | Live: a `Match User ... Address` block, directly and in a nested `Include`, was refused with and without the address |
| `pubkeyauthentication` and the authorized-keys path were not checked | Both are required in all three paths, with `%h`, `%u` and relative paths resolved | Live: a wrong `AuthorizedKeysFile` ended in an error; `/home/%u/.ssh/authorized_keys` was accepted by all three |
| A failed reload could look like success on a later run, and an inactive server went unnoticed | Every check after the drop-in is guarded; SSH is reloaded when running and started when neither it nor its socket is | Live: stopped SSH units were started on Ubuntu and RHEL |
| A malformed `rounds=` value would have been installed | Rounds must be 1000 to 999999999 without leading zeros | Live: `rounds=0` was refused |
| Ownership and modes were not enforced when the content already matched | Enforced on every run, as the account for its own files | Live: modes 0777 and 0666 were reset |
| A key the server rejects could replace every working key | At least one key must match an accepted algorithm, any of the RSA ones for an RSA key, and the larger of 2048 bits and `RequiredRSASize`, in all three paths | Live: Ed25519-only and 1024-bit key lists were refused; under `rsa-sha2-256` only and `RequiredRSASize 3072`, the playbook accepted RSA 4096 keys and refused a 1024-bit one |
| cloud-init reported success after failures and missed a missing key, and removed its drop-in after any failed check | Failures are collected and end in an error; the drop-in is set aside only when it is what makes `sshd -t` fail | Live: the placeholder VM reported `status: error`; with a nested address rule the drop-in stayed in place |
| The Azure administrator named `svc_ansible` would keep passwordless sudo | `targets.yml` refuses that name, and cloud-init reports it | Offline: the assertion; not provisioned |
| Smaller issues: check order, YAML-breaking key comments, the 4 KB output limit | Checks reordered, the portal instructions updated, the result line printed last | Live runs above |
| Documentation: the local-content command ran from the wrong folder without credentials; the managed example dropped the service key; seeded exceptions named only Enterprise Linux; template limits and counts were out of date | Corrected in chapters 4, 6, 9, 13 and 3b and in the catalog | Offline checks |

## Not established

- Rocky Linux on Azure, ARM64 sizes, Trusted Launch or confidential VMs, and
  other regions.
- FIPS mode, Ubuntu FIPS kernels, and STIG applied to the controllers.
- The per-target Vault option for sudo passwords on a seeded controller; the
  test used one shared sudo credential on the inventory.
- A comparison with DISA's SCAP Compliance Checker on the same targets.
