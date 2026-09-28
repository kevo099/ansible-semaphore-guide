# Security baseline catalog

Use this page to choose a security baseline for a platform, find its publisher
and tools, and select a profile with this guide's Ansible playbooks. Start with
the system owner's requirements, then match the operating system, product
version and role. [Chapter 9](../09-security-benchmarks.md) covers preparation,
remediation, recovery and reading the results.

## How to read this page

**September 2026 snapshot, checked on September 28.** Versions change. A
publisher's benchmark, a scanner's content and a target's installed package can
have different versions. A manual STIG and its SCAP benchmark are separate
releases. The tables identify which was verified; they do not promise that
every listed version is implemented by the guide. A scan is evidence, not
compliance: manual checks, organizational controls, applicability and exceptions
still need review.

## Families and how they relate

Work from the obligation to the evidence: identify the system's scope, select
the applicable controls, choose a product baseline, then assess its implementation.
The families below operate at different points in that process.

| Family | What it means for this lab |
| --- | --- |
| [DISA STIGs and SRGs](https://public.cyber.mil/stigs/) | A Security Requirements Guide describes requirements for a technology family. A Security Technical Implementation Guide applies them to a product, particularly for US defense systems. Select the product's STIG and record its version/release. |
| [CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks/cis-benchmarks-faq) | Product configuration recommendations. Level 1 aims for practical hardening with limited operational impact; Level 2 adds restrictions requiring more suitability testing. Some products also have a CIS STIG profile. Its CIS document version is separate from DISA's release number. |
| [CIS Controls v8.1](https://www.cisecurity.org/controls/v8-1) | Eighteen organizational Controls, with Safeguards prioritized through Implementation Groups. These groups are different from Benchmark Levels 1 and 2. A server benchmark implements only part of this work. |
| [NIST SP 800-53 Rev. 5](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final) | A security and privacy control catalog; release 5.2.0 was published in August 2025. Its companion SP 800-53B defines control baselines. STIG/CIS findings can support control evidence; they do not authorize a system. |
| [NIST SP 800-171 Rev. 3](https://csrc.nist.gov/pubs/sp/800/171/r3/final) | Requirements for protecting Controlled Unclassified Information in nonfederal systems. The applicable contract or program can specify an earlier revision. Inspect a profile named `cui` before assuming which revision it covers. |
| [NIST SP 800-70 Rev. 5 and NCP](https://csrc.nist.gov/pubs/sp/800/70/r5/final) | The May 2026 publication explains selecting and maintaining configuration checklists through the National Checklist Program. NCP helps locate checklists; it is not another hardening profile. |
| [SCAP](https://csrc.nist.gov/pubs/sp/800/126/r4/final) | Specifications for machine-readable security content and assessment. SCAP 1.4 became final in June 2026; the DISA files tested here use SCAP 1.3. Format support depends on the scanner and content. |
| [CMMC](https://dodcio.defense.gov/CMMC/About/) | A defense contractor assessment program covering Federal Contract Information and CUI. The official overview identifies 110 SP 800-171 Rev. 2 requirements for Level 2. A Linux profile cannot perform the organizational assessment. |
| [FedRAMP](https://www.fedramp.gov/rev5/agency-authorization/) | Assessment of cloud service offerings for US federal use. The Rev5 path uses NIST SP 800-53 Rev. 5 controls. Follow the applicable program path and scope; a hardened VM is only one component. |
| [PCI DSS v4.0.1](https://www.pcisecuritystandards.org/document_library/) | Payment account data security requirements. A `pci-dss` host profile checks a technical subset; it cannot validate the whole cardholder data environment. |
| [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html) | Administrative, physical and technical safeguards for electronic protected health information. HHS distinguishes the rule in effect from its proposed update. An OS `hipaa` profile covers only host settings. |
| [Essential Eight](https://www.cyber.gov.au/business-government/asds-cyber-security-frameworks/essential-eight/essential-eight-maturity-model) | Australian mitigation strategies with maturity levels 0–3; the verified model is November 2023. Patching, access, application control and recovery require work beyond an `e8` OS profile. |
| [ANSSI BP-028](https://messervices.cyber.gouv.fr/documents-guides/fr_np_linux_configuration-v2.0.pdf) | French GNU/Linux hardening guidance, verified v2.0 from October 2022. Its minimal, intermediate, reinforced and high levels support different system needs. SSG implements product-specific selections. |
| [BSI IT-Grundschutz](https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Grundschutz/BSI_Standards/standard_200_2.pdf?__blob=publicationFile&v=2) | German information-security management methodology and requirements. Standard 200-2 v1.0 is the verified methodology reference. SSG's `bsi` profile addresses a small system-configuration subset. |
| [Microsoft security baselines](https://www.microsoft.com/en-us/download/details.aspx?id=55319) | Vendor recommendations and configuration packages for Windows, Microsoft 365 Apps and Edge, distributed through the Security Compliance Toolkit (SCT). Match the package to the product release and role. |
| [OSPP and Common Criteria](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/security_hardening/using-the-system-wide-cryptographic-policies_security-hardening) | A Protection Profile defines requirements for product evaluation. An SSG `ospp` profile or `FIPS:OSPP` crypto policy does not certify an arbitrary installation. The evaluated product/version and its configuration guidance matter. |

Choose CIS Level 1 for an initial general hardening exercise when no other
baseline is required. Choose STIG when practicing that product's defense
requirements. Treat this as a learning recommendation: there is no universal
ordering in which STIG is simply a level above CIS Level 2. Compare the actual
rules and parameters before combining or replacing profiles.

## Baselines by platform

This is a practical shortlist for readers asking about the most-used baselines.
**Popularity is an inference from platform coverage and available tooling.** No
September 2026 request counts or global adoption ranking were verified. CIS
versions below are the publisher's benchmark listings. DISA entries explicitly
identify downloaded SCAP content, listed SCAP releases or dated manual releases.

### Linux

| Platform | Verified benchmarks | Use with this guide |
| --- | --- | --- |
| RHEL 8 / 9 / 10 | [CIS](https://www.cisecurity.org/benchmark/red_hat_linux) 4.0.0 / 3.0.0 / 1.0.1. RHEL 9 DISA SCAP V2R9 was downloaded in the Azure run. | Playbooks accept RHEL 9. Use its native SSG data stream or matching local SCAP content. |
| Ubuntu 22.04 / 24.04 LTS | [CIS](https://www.cisecurity.org/benchmark/ubuntu_linux) 3.0.0 / 2.0.0. Ubuntu 24.04 DISA SCAP V1R5 was downloaded; installed USG supplied STIG V1R1. | Playbooks accept Ubuntu 24.04. USG needs Ubuntu Pro access; local SCAP uses OpenSCAP. |
| AlmaLinux 9 | [CIS](https://www.cisecurity.org/benchmark/almalinuxos_linux) 3.0.0. DISA's July manual release was V1R7. | Use AlmaLinux's own package. Its SSG STIG label must not be equated with the independent DISA manual revision. |
| Rocky Linux 9 | [CIS](https://www.cisecurity.org/benchmark/rocky_linux) 3.0.0. No independently named DISA Rocky STIG was verified. | The guide selects Rocky's own SSG stream; its STIG profile is titled for RHEL 9. |

The [DISA July 2026 announcement](https://www.cyber.mil/stigs/stig-announcements)
also lists Ubuntu 24.04 **manual V1R6**. That does not establish that a V1R6
SCAP file exists. The [September 2026 Azure run](../validation/2026-09-onboard-stig.md)
retrieved RHEL 9 SCAP V2R9 and Ubuntu 24.04 SCAP V1R5 without login; the tested
V2R10 and V1R6 SCAP URLs were absent on September 28.

### Windows

| Platform | Verified benchmarks | Selection point |
| --- | --- | --- |
| Windows Server 2022 / 2025 | [CIS](https://www.cisecurity.org/benchmark/microsoft_windows_server) 5.1.0 / 2.1.0; separate stand-alone benchmarks 2.0.0 / 2.0.0. DISA SCAP listings: V2R10 / V1R1. | Distinguish domain controller, member server and stand-alone roles. |
| Windows 11 | [CIS](https://www.cisecurity.org/benchmark/microsoft_windows_desktop) Enterprise 5.1.0; stand-alone 5.0.0. DISA SCAP listing: V2R10. | Match edition, management model and supported OS release. |
| Microsoft vendor baselines | [SCT](https://www.microsoft.com/en-us/download/details.aspx?id=55319) lists Server 2022 and Server 2025, plus Windows 11 23H2 / 24H2 / 25H2 packages. The Server 2025 package is labeled 2602. | Use the vendor package for the matching release. This is a separate baseline from CIS or STIG. |

The [DISA SCAP listings](https://www.cyber.mil/stigs/SCAP) identify the Windows
releases above in August 2026. Their version numbers must not be substituted
for manual STIG revisions. Windows automation is outside these Linux playbooks.

### Containers and Kubernetes

| Platform | Verified benchmarks | Selection point |
| --- | --- | --- |
| Kubernetes | [CIS Kubernetes](https://www.cisecurity.org/benchmark/kubernetes) 2.0.1; EKS, AKS, GKE, GKE Autopilot and OpenShift benchmarks 2.0.0 each. DISA SCAP listing: V2R5, July 2026. | Select the distribution and deployment model; managed control planes change what you can assess. |
| OpenShift / RKE2 | [DISA's July 2026 manual announcement](https://www.cyber.mil/stigs/stig-announcements) lists V2R6 / V2R7. | Product-specific STIGs; these are dated releases, not a claim about the latest archive. |
| Docker | [CIS Docker](https://www.cisecurity.org/benchmark/docker) 1.8.0. | Assess the Docker host and runtime configuration separately from application images and the host OS baseline. |

### Cloud

| Platform | Verified benchmark | What it targets |
| --- | --- | --- |
| AWS | [CIS AWS Foundations 7.0.0](https://www.cisecurity.org/benchmark/amazon_web_services) | Account and service configuration; guest OS hardening remains separate. |
| Azure | [CIS Azure Foundations 6.0.0](https://www.cisecurity.org/benchmark/azure) | Cloud configuration; an Azure VM's STIG scan does not assess the subscription. |
| Google Cloud | [CIS Google Cloud Platform Foundation 5.0.0](https://www.cisecurity.org/benchmark/google_cloud_computing_platform) | Cloud configuration; use the separate GKE benchmark for Kubernetes. |

### Network devices

| Platform | Verified benchmark | Selection point |
| --- | --- | --- |
| Cisco | [CIS](https://www.cisecurity.org/benchmark/cisco): IOS 17.x 2.0.0; IOS XE 17.x 2.2.1; NX-OS 1.2.0. | Match the OS family, release and routing/switching role. Exact current DISA component revisions were not verified. |
| Palo Alto Networks | [CIS Firewall 11 1.2.0](https://www.cisecurity.org/benchmark/palo_alto_networks). | Match the appliance software release; do not reuse a Linux host profile. |

### Applications

| Platform | Verified benchmark | Selection point |
| --- | --- | --- |
| Apache HTTP Server 2.4 | [CIS 2.4.0](https://www.cisecurity.org/benchmark/apache_http_server). | Assess server/site settings as well as the underlying OS. |
| PostgreSQL 16 / 17 / 18 | [CIS](https://www.cisecurity.org/benchmark/postgresql) 1.1.0 / 1.1.0 / 1.0.0. DISA's July manual announcement lists Crunchy Data Postgres 16 V1R3. | A vendor-specific STIG does not establish applicability to every PostgreSQL deployment. |
| SQL Server 2022 / 2025 | [CIS](https://www.cisecurity.org/benchmark/microsoft_sql_server) 1.3.0 / 1.0.0. | Database configuration and permissions need their own assessment. |
| Microsoft 365 Apps / Edge | [SCT's August 2026 download listing](https://www.microsoft.com/en-us/download/details.aspx?id=55319) includes baselines 2512 / 151. | These are application settings; they do not assess an entire Microsoft 365 tenant. |

## Tooling map

A scanner, its benchmark content and a remediation tool are separate choices.
Check the content version supported by the tool before comparing it with a
publisher's current listing. License notes here identify access conditions;
read the selected release's terms before redistributing content.

| Tool | Job | License and access |
| --- | --- | --- |
| [OpenSCAP](https://github.com/OpenSCAP/openscap) and [SCAP Security Guide / ComplianceAsCode](https://github.com/ComplianceAsCode/content) | OpenSCAP evaluates SCAP content and can execute included fixes. SSG supplies product profiles and remediation content. This is the guide's Enterprise Linux path. | OpenSCAP: LGPL-2.1; SSG: BSD-3-Clause. Vendor packages can differ from upstream archives. |
| [Ubuntu Security Guide (`usg`)](https://github.com/canonical/ubuntu-security-guide) | Canonical's audit, fix and tailoring interface for Ubuntu CIS/STIG content. | GPLv3 source; supported package access through Ubuntu Pro. A Pro entitlement and available benchmark content are separate from the source license. |
| [DISA SCC](https://www.cyber.mil/stigs/SCAP) and [STIG Viewer](https://www.cyber.mil/stigs/srg-stig-tools) | SCAP Compliance Checker evaluates SCAP benchmarks; STIG Viewer manages checklists and human review. Viewer is not a scanner. | Public tools/downloads; [SCC source licensing is separate](https://www.niwcatlantic.navy.mil/Media/News-Stories/Article/3432729/naval-information-warfare-center-atlantic-signs-five-year-software-licensing-ag/). Public download does not make every tool open source. The tested DISA SCAP ZIPs need no login. |
| [CIS-CAT](https://www.cisecurity.org/cybersecurity-tools/cis-cat-pro) | CIS assessment tooling and reports; confirm benchmark coverage for the chosen release. | Pro requires SecureSuite membership. Lite has limited coverage and terms for [internal, non-commercial use](https://learn.cisecurity.org/cis-cat-trial-terms). Download access does not grant unrestricted redistribution rights. |
| [ansible-lockdown](https://github.com/ansible-lockdown/RHEL9-STIG) | Product-specific CIS/STIG Ansible remediation roles; audit integration varies by repository. The guide does not call these roles. | The inspected RHEL9-STIG role is MIT. Check each role's license, supported OS and implemented benchmark revision. |
| [RHEL System Roles](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/automating_system_administration_by_using_rhel_system_roles/intro-to-rhel-system-roles_automating-system-administration-by-using-rhel-system-roles) | Reusable administration roles for logging, networking, crypto policy and other services. Installing them does not apply an SSG benchmark. | Open-source roles with component-specific licenses; supported RHEL distribution follows Red Hat subscription/support terms. |
| [PowerSTIG](https://github.com/microsoft/PowerStig) and Microsoft SCT | PowerSTIG uses PowerShell DSC for supported STIG settings. SCT supplies Microsoft baseline packages, Policy Analyzer and LGPO. | PowerSTIG: MIT. SCT: downloadable Microsoft tools/packages under their supplied terms. Coverage depends on the specific product/version. |
| [kube-bench](https://github.com/aquasecurity/kube-bench) | Runs supported CIS Kubernetes checks; choose the correct benchmark/platform mapping. | Apache-2.0. Tool support may lag the publisher; inaccessible or manual checks still need review. |
| [Docker Bench for Security](https://github.com/docker/docker-bench-security) | Checks Docker host/runtime configuration. Its README identifies implemented CIS Docker 1.6.0, while the publisher lists 1.8.0. | Apache-2.0. Record the tool's actual coverage. |
| [Prowler](https://github.com/prowler-cloud/prowler) | Assesses cloud configuration and maps findings to supported compliance frameworks. | Apache-2.0 open-source project; hosted offerings have separate terms. A framework mapping is not a complete assessment. |

## Profiles usable with this guide

The [audit playbook](../../playbooks/stig-audit.yml) and
[apply playbook](../../playbooks/stig-apply.yml) accept the variables below.
Set them as Ansible extra variables with `-e`, or in the Semaphore template's
variable group JSON. Ordinary inventory variables do not override the defaults
declared inside these plays. The task names still say STIG when you select CIS.

| Target allowed by the guide | Vendor content selected by default | Profile variable |
| --- | --- | --- |
| RHEL 9 | `/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml` | `stig_profile_el` |
| AlmaLinux 9 | `/usr/share/xml/scap/ssg/content/ssg-almalinux9-ds.xml` | `stig_profile_el` |
| Rocky Linux 9 | `/usr/share/xml/scap/ssg/content/ssg-rl9-ds.xml` | `stig_profile_el` |
| Ubuntu 24.04 | Installed USG content | `stig_usg_profile` |

The targets must use systemd and meet the guide's bootstrap prerequisites.
Changing a profile does not extend the supported OS list. Audit can install
scanner/content packages and writes reports, but changes no security policy.
Both playbooks refuse check mode, including Semaphore Dry Run.

### RHEL and AlmaLinux 9 SSG IDs

These complete IDs were present in the recorded RHEL 9 package
`scap-security-guide-0.1.82-2.el9_8` and the
[AlmaLinux 9 vendor RPM](https://repo.almalinux.org/almalinux/9/AppStream/x86_64/os/Packages/scap-security-guide-0.1.82-2.el9_8.alma.1.noarch.rpm)
inspected in September 2026. This inventory establishes profile availability;
the Azure run exercised `stig`, not every profile in the table. Check the
package actually installed on your target with `rpm -q scap-security-guide`
and `oscap info` on its own data stream.

| Baseline | Exact value for `stig_profile_el` |
| --- | --- |
| STIG, the guide's default | `xccdf_org.ssgproject.content_profile_stig` |
| STIG with GUI | `xccdf_org.ssgproject.content_profile_stig_gui` |
| CIS Level 1 Server | `xccdf_org.ssgproject.content_profile_cis_server_l1` |
| CIS Level 2 Server | `xccdf_org.ssgproject.content_profile_cis` |
| CIS Level 1 Workstation | `xccdf_org.ssgproject.content_profile_cis_workstation_l1` |
| CIS Level 2 Workstation | `xccdf_org.ssgproject.content_profile_cis_workstation_l2` |
| ANSSI minimal | `xccdf_org.ssgproject.content_profile_anssi_bp28_minimal` |
| ANSSI intermediate | `xccdf_org.ssgproject.content_profile_anssi_bp28_intermediary` |
| ANSSI reinforced | `xccdf_org.ssgproject.content_profile_anssi_bp28_enhanced` |
| ANSSI high | `xccdf_org.ssgproject.content_profile_anssi_bp28_high` |
| BSI SYS.1.1 / SYS.1.3 subset | `xccdf_org.ssgproject.content_profile_bsi` |
| Spanish CCN-STIC basic | `xccdf_org.ssgproject.content_profile_ccn_basic` |
| Spanish CCN-STIC intermediate | `xccdf_org.ssgproject.content_profile_ccn_intermediate` |
| Spanish CCN-STIC advanced | `xccdf_org.ssgproject.content_profile_ccn_advanced` |
| Draft NIST SP 800-171 configuration | `xccdf_org.ssgproject.content_profile_cui` |
| Essential Eight subset | `xccdf_org.ssgproject.content_profile_e8` |
| Australian ISM Official subset | `xccdf_org.ssgproject.content_profile_ism_o` |
| HIPAA host subset | `xccdf_org.ssgproject.content_profile_hipaa` |
| OSPP configuration | `xccdf_org.ssgproject.content_profile_ospp` |
| PCI DSS host subset | `xccdf_org.ssgproject.content_profile_pci-dss` |

**CIS Level 2 Server is `..._profile_cis`, not `..._profile_cis_server_l2`.**
The `cui` profile is explicitly draft; do not label it SP 800-171 Rev. 3 or
CMMC coverage. AlmaLinux's inspected package describes its STIG as V2R9;
equivalence to DISA's separate AlmaLinux V1R7 manual was not established.
That package's CIS profiles describe benchmark 2.0.0, while the publisher
lists 3.0.0.
Use the native vendor data stream rather than another distribution's file to
obtain a preferred label. [Red Hat's scanning guide](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/security_hardening/scanning-the-system-for-configuration-compliance-and-vulnerabilities_security-hardening)
explains inspecting and selecting SSG profiles.

### Ubuntu 24.04 USG names

The September 2026 Azure run used the Ubuntu Pro image
`Canonical:ubuntu-24_04-lts:ubuntu-pro`, which attached Pro automatically.
After `pro enable usg`, USG 24.04.8 listed the following profiles. Other images
need their own supported Pro attachment; the playbook does not attach them.

| Exact value for `stig_usg_profile` | Content observed |
| --- | --- |
| `cis_level1_server-v1.0.0` | CIS Ubuntu 24.04 1.0.0, Level 1 Server |
| `cis_level2_server-v1.0.0` | CIS Ubuntu 24.04 1.0.0, Level 2 Server |
| `cis_level1_workstation-v1.0.0` | CIS Ubuntu 24.04 1.0.0, Level 1 Workstation |
| `cis_level2_workstation-v1.0.0` | CIS Ubuntu 24.04 1.0.0, Level 2 Workstation |
| `cis_level1_server_ec2-v1.0.0` | CIS Ubuntu 24.04 1.0.0, EC2 variant |
| `stig-v1r1` | STIG/ubuntu2404 V1R1 |

The guide defaults to `disa_stig`; that alias worked in the run and maps to
`stig-v1r1` in the observed metadata. The EC2 profile's presence does not make
it the right selection for Azure. Run `usg list` and inspect the installed
metadata before choosing. USG's CIS 1.0.0 content is distinct from the
publisher's Ubuntu 24.04 benchmark 2.0.0 listed above.

### Run a vendor audit

**Where: controller, in `/opt/ansible-lab`, with the prepared inventory and
connection credentials.** Select a host that exists in your inventory. The
examples use your own key from [chapter 4](../04-access.md#step-1-generate-the-automation-key)
and ask for the targets' sudo password, as [chapter 5](../05-cli-lessons.md)
does; with the Vault option, use `--ask-vault-pass` instead of `-K`. They
choose RHEL CIS Level 1, AlmaLinux CIS Level 2 and Ubuntu CIS Level 1.

```bash
cd /opt/ansible-lab
/opt/ansible-venv/bin/ansible-playbook -i inventories/lab.ini playbooks/stig-audit.yml \
  --limit lab-rhel \
  --private-key ~/.ssh/ansible_lab -K \
  -e '{"stig_profile_el": "xccdf_org.ssgproject.content_profile_cis_server_l1"}'

/opt/ansible-venv/bin/ansible-playbook -i inventories/lab.ini playbooks/stig-audit.yml \
  --limit lab-alma \
  --private-key ~/.ssh/ansible_lab -K \
  -e '{"stig_profile_el": "xccdf_org.ssgproject.content_profile_cis"}'

/opt/ansible-venv/bin/ansible-playbook -i inventories/lab.ini playbooks/stig-audit.yml \
  --limit lab-ubuntu \
  --private-key ~/.ssh/ansible_lab -K \
  -e '{"stig_usg_profile": "cis_level1_server-v1.0.0"}'
```

For the vendor STIG, omit the profile override to use the defaults above.
The vendor EL path omits remote resource retrieval by default; checks needing
those resources can report `notchecked`. To enable it, add
`"stig_fetch_remote_resources": true` to the extra-variable JSON and provide
the target's required network access. This flag does not change the local
SCAP command below.

For remediation, follow [chapter 9's seeded templates](../09-security-benchmarks.md#the-seeded-stig-templates).
Keep the exact same profile for before and after scans. `stig-apply.yml` runs
the vendor data stream's embedded fixes on EL and `usg fix` on Ubuntu. It
requires one target, a recovery acknowledgment (`stig_confirm: true` as a JSON
boolean from the CLI) and a separate `allow_reboot: true` decision for reboot.
Profile availability alone does not establish that every selected rule has a fix.

### DISA SCAP files and profile IDs

These two public ZIP downloads were verified in the September 2026 Azure run:

| Platform | Downloaded SCAP 1.3 benchmark |
| --- | --- |
| RHEL 9 | [U_RHEL_9_V2R9_STIG_SCAP_1-3_Benchmark.zip](https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/U_RHEL_9_V2R9_STIG_SCAP_1-3_Benchmark.zip) |
| Ubuntu 24.04 LTS | [U_CAN_Ubuntu_24-04_LTS_V1R5_STIG_SCAP_1-3_Benchmark.zip](https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/U_CAN_Ubuntu_24-04_LTS_V1R5_STIG_SCAP_1-3_Benchmark.zip) |

Each ZIP held one SCAP data stream XML and these eleven profile IDs. Select the
profile required for your system; the MAC/classification labels are not CIS
levels. CAT I Only and Disable Slow Rules change the assessment scope and
must be identified in the results.

```text
xccdf_mil.disa.stig_profile_MAC-1_Classified
xccdf_mil.disa.stig_profile_MAC-1_Public
xccdf_mil.disa.stig_profile_MAC-1_Sensitive
xccdf_mil.disa.stig_profile_MAC-2_Classified
xccdf_mil.disa.stig_profile_MAC-2_Public
xccdf_mil.disa.stig_profile_MAC-2_Sensitive
xccdf_mil.disa.stig_profile_MAC-3_Classified
xccdf_mil.disa.stig_profile_MAC-3_Public
xccdf_mil.disa.stig_profile_MAC-3_Sensitive
xccdf_mil.disa.stig_profile_CAT_I_Only
xccdf_mil.disa.stig_profile_Disable_Slow_Rules
```

Follow [chapter 9's local SCAP procedure](../09-security-benchmarks.md#scan-with-a-local-scap-content-file)
to download, inspect and place the XML inside the lab folder. Then pass
`stig_content_file` and `stig_content_profile`. For example, after inspecting
that file with `oscap info` and selecting its MAC-1 Public profile:

```bash
cd /opt/ansible-lab
/opt/ansible-venv/bin/ansible-playbook -i inventories/lab.ini playbooks/stig-audit.yml \
  --limit lab-rhel \
  --private-key ~/.ssh/ansible_lab -K \
  -e '{"stig_content_file": "content/U_RHEL_9_V2R9_STIG_SCAP_1-3_Benchmark.xml", "stig_content_profile": "xccdf_mil.disa.stig_profile_MAC-1_Public"}'
```

This selects OpenSCAP on either supported OS family, bypassing the vendor
SSG/USG profile selection. Match the content to the target: a benchmark for
another product can return `notapplicable`, which does not demonstrate passing
checks. In the run, the RHEL 9 DISA benchmark returned all 392 rules as not
applicable on AlmaLinux 9.8. The tested DISA content contains no remediation fixes, and
`stig-apply.yml` refuses local content.

Seeded controllers include **STIG audit, local SCAP content**, using the
**Local SCAP content** variable group. Replace both placeholders with the
reviewed file path and full profile ID; the playbook refuses the placeholders.
Choose matching targets in Limit and leave Dry Run off.

## What the live run establishes

The [September 2026 Azure run](../validation/2026-09-onboard-stig.md) exercised
vendor STIG remediation with a reboot on three guests. These are before/after
outcome counts for each guest's content, not comparable compliance percentages.

| Target | Failed before → after | Passed before → after |
| --- | --- | --- |
| Ubuntu 24.04 Pro, USG `disa_stig` | 67 → 8 | 54 → 209 |
| AlmaLinux 9.8, vendor SSG `stig` | 268 → 22 | 155 → 406 |
| RHEL 9.8 PAYG, vendor SSG `stig` | 262 → 15 | 170 → 420 |

A second RHEL pass through Semaphore recorded 16 → 13 failures. It is a
separate before/after observation; preserve the reports rather than treating
these counts as a single monotonic sequence. Remaining failures, manual checks
and checks made applicable by newly installed packages still require review.
The DISA downloads and profile inventory are separate evidence from these
vendor remediation results.

## What this guide does not cover

- CMMC assessments, FedRAMP authorization/certification, PCI validation or
  organization-wide HIPAA, Essential Eight or IT-Grundschutz compliance.
- Windows, Kubernetes, cloud-account, network-device or application benchmark
  automation through these Linux playbooks.
- Extending the playbooks to other OS releases merely by changing a profile.
- Automatic remediation from the tested DISA SCAP files, or complete automated
  coverage of manual and organizational requirements.
- A universal ranking of baseline strength, formal product certification or
  proof that a crypto-policy setting enables a validated FIPS deployment.
