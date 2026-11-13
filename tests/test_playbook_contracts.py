"""Offline checks that the lesson playbooks agree with each other and with the seeder."""

import ast
import base64
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import jinja2
from jinja2.nativetypes import NativeEnvironment
import yaml


ROOT = Path(__file__).resolve().parents[1]
# Each accepted Enterprise Linux distribution and the data stream its own
# scap-security-guide package ships. Update both playbooks and this table together.
VENDOR_DATA_STREAMS = {"RedHat": "rhel9", "AlmaLinux": "almalinux9", "Rocky": "rl9"}
STIG_PLAYBOOKS = ("playbooks/stig/audit.yml", "playbooks/stig/apply.yml")
# Every playbook with plays of its own is one folder below playbooks/, the folder of its
# feature; tasks/ and vars/ hold what they share. The files directly in playbooks/ and
# below stig/<system>/ only import one of them.
FEATURE_PLAYBOOKS = sorted(path for path in (ROOT / "playbooks").glob("*/*.yml") if path.parent.name not in ("tasks", "vars"))


def tasks(relative):
    return yaml.safe_load((ROOT / relative).read_text())


def named(task_list, prefix):
    return next(t for t in task_list if t.get("name", "").startswith(prefix))


def walk(task_list, inherited=None):
    """Yield each task with the become and delegate_to it inherits, through blocks and imports."""
    for task in task_list or []:
        effective = dict(inherited or {}, **{key: task[key] for key in ("become", "delegate_to") if key in task})
        if "ansible.builtin.import_tasks" in task:
            # The path is relative to the playbook's own folder, one below playbooks/.
            yield from walk(tasks(os.path.normpath(f"playbooks/feature/{task['ansible.builtin.import_tasks']}")), effective)
        elif "block" in task:
            for section in ("block", "rescue", "always"):
                yield from walk(task.get(section), effective)
        else:
            yield dict(task, **effective)


def package_tasks(data):
    """Yield every apt or dnf task in a parsed playbook or task file."""
    if isinstance(data, list):
        for item in data:
            yield from package_tasks(item)
    elif isinstance(data, dict):
        if {"ansible.builtin.apt", "ansible.builtin.dnf"} & data.keys():
            yield data
        for value in data.values():
            yield from package_tasks(value)


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "controller" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native(expression, **variables):
    """Render one playbook expression the way Ansible does: keeping its native type."""
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters["from_json"] = json.loads
    return environment.from_string(expression).render(**variables)


class DataStreamTests(unittest.TestCase):
    def accepted_enterprise_linux(self):
        task = named(tasks("playbooks/tasks/preflight.yml"), "Reject operating systems outside this lesson")
        condition = task["ansible.builtin.assert"]["that"][0]
        return set(ast.literal_eval(re.search(r"\['distribution'\] in (\[[^\]]*\])", condition).group(1)))

    def datastream_expression(self):
        task = next(t for t in tasks("playbooks/tasks/stig_scan.yml")
                    if "stig_datastream" in t.get("ansible.builtin.set_fact", {}))
        return task["ansible.builtin.set_fact"]["stig_datastream"]

    def test_preflight_accepts_exactly_the_distributions_the_scan_maps(self):
        mapping = ast.literal_eval(re.search(r"\{\{ (\{[^}]*\})\[", self.datastream_expression()).group(1))
        self.assertEqual(self.accepted_enterprise_linux(), set(mapping))
        self.assertEqual(set(mapping), set(VENDOR_DATA_STREAMS))

    def test_each_distribution_uses_its_own_vendor_data_stream(self):
        template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(self.datastream_expression())
        for distribution, short in VENDOR_DATA_STREAMS.items():
            with self.subTest(distribution=distribution):
                path = template.render(ansible_facts={"distribution": distribution})
                self.assertNotRegex(path, r"\s")
                self.assertEqual(path, f"/usr/share/xml/scap/ssg/content/ssg-{short}-ds.xml")
        with self.assertRaises(jinja2.UndefinedError):
            template.render(ansible_facts={"distribution": "CentOS"})


class ApprovalTests(unittest.TestCase):
    def stig_confirm(self):
        return tasks("playbooks/stig/apply.yml")[0]["vars"]["stig_confirm"]

    def test_seeded_recovery_answer_is_the_one_stig_apply_accepts(self):
        prompt = load("seed-semaphore").RECOVERY_PROMPT[0]
        for choice in prompt["values"]:
            with self.subTest(answer=choice["value"]):
                self.assertIs(native(self.stig_confirm(), **{prompt["name"]: choice["value"]}), True)

    def test_other_answers_are_refused(self):
        prompt = load("seed-semaphore").RECOVERY_PROMPT[0]
        self.assertIs(native(self.stig_confirm()), False)
        for answer in ("", "snapshot ready", prompt["values"][0]["name"]):
            with self.subTest(answer=answer):
                self.assertIs(native(self.stig_confirm(), **{prompt["name"]: answer}), False)


class CheckModeTests(unittest.TestCase):
    def test_stig_playbooks_refuse_check_mode_before_connecting(self):
        for playbook in STIG_PLAYBOOKS:
            with self.subTest(playbook=playbook):
                play = tasks(playbook)[0]
                self.assertFalse(play["gather_facts"])
                names = [t["name"] for t in play["pre_tasks"]]
                refusal = next((i for i, t in enumerate(play["pre_tasks"])
                                if "not ansible_check_mode" in t.get("ansible.builtin.assert", {}).get("that", [])),
                               None)
                self.assertIsNotNone(refusal, "no pre-task refuses check mode")
                # The preflight gathers facts over SSH, so the refusal must come first.
                self.assertLess(refusal, names.index("Check scope and supported operating system"))
                self.assertIn("always", play["pre_tasks"][refusal]["tags"])


class SummaryReportTests(unittest.TestCase):
    """The summarizer exits 2 after printing its JSON when error/unknown outcomes exist."""

    def report(self, summary):
        task = named(tasks("playbooks/tasks/stig_scan.yml"), "Report the scan outcome counts")
        older = native(task["vars"]["stig_summary_older"], stig_summary=summary)
        return native(task["ansible.builtin.debug"]["msg"], stig_summary=summary, stig_summary_older=older)

    def warns(self, summary):
        task = named(tasks("playbooks/tasks/stig_scan.yml"), "Warn about scanner errors or unknown outcomes")
        # Ansible evaluates a list of conditions in order and stops at the first false one.
        return all(native("{{ " + condition + " }}", stig_summary=summary) for condition in task["when"])

    def summary(self, rc, flagged):
        stdout = json.dumps({"outcome_instances": {"pass": 1}, "has_scanner_errors_or_unknowns": flagged})
        return {"rc": rc, "stdout": stdout, "stderr": "", "msg": ""}

    def test_counts_are_reported_with_and_without_error_outcomes(self):
        for rc, flagged in ((0, False), (2, True)):
            with self.subTest(rc=rc):
                result = self.report(self.summary(rc, flagged))
                self.assertIsInstance(result, dict)
                self.assertIs(result["has_scanner_errors_or_unknowns"], flagged)
                self.assertIs(self.warns(self.summary(rc, flagged)), flagged)

    def test_a_summarizer_that_printed_nothing_is_reported_as_unavailable(self):
        missing_script = {"rc": 2, "stdout": "", "stderr": "can't open file", "msg": "non-zero return code"}
        invalid_xml = {"rc": 1, "stdout": "", "stderr": "Cannot summarize assessment", "msg": "non-zero return code"}
        for summary in (missing_script, invalid_xml):
            with self.subTest(rc=summary["rc"]):
                result = self.report(summary)
                self.assertTrue(result.startswith("Summary unavailable"))
                self.assertIn(summary["stderr"], result)
                self.assertNotIn("older than this playbook", result)
                self.assertFalse(self.warns(summary))

    def test_an_earlier_copy_of_the_script_is_named_as_the_cause(self):
        # A lab folder that kept its own, earlier summarize_xccdf.py: argparse refuses the options it does not know.
        earlier = {"rc": 2, "stdout": "", "msg": "non-zero return code",
                   "stderr": "usage: summarize_xccdf.py [-h] [--result-id RESULT_ID] xml\n"
                             "summarize_xccdf.py: error: unrecognized arguments: --findings /x/audit-findings.csv"}
        result = self.report(earlier)
        self.assertTrue(result.startswith("Summary unavailable; read the HTML report. The lab folder's "
                                          "scripts/summarize_xccdf.py is older than this playbook; take the guide's copy. "
                                          "usage: summarize_xccdf.py"), result)
        self.assertFalse(self.warns(earlier))


class MissingResultsTests(unittest.TestCase):
    """The usg scan never fails on its own, so the check for its results must carry usg's error."""

    def message(self, usg_result):
        task = named(tasks("playbooks/tasks/stig_scan.yml"), "Stop when no results were produced")
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        variables = {"inventory_hostname": "lab-ubuntu", "stig_usg_profile": "disa_stig", "stig_scan_usg": usg_result}
        # Ansible templates fail_msg even when the assertion passes, so every path must render.
        variables["stig_usg_output"] = environment.from_string(task["vars"]["stig_usg_output"]).render(**variables)
        return environment.from_string(task["ansible.builtin.assert"]["fail_msg"]).render(**variables)

    def test_a_failed_usg_scan_shows_its_exit_code_and_error(self):
        error = "Error: profile disa_stig is not available in this channel"
        message = self.message({"rc": 1, "stdout_lines": [], "stderr_lines": [error]})
        self.assertIn("usg audit disa_stig exited 1.", message)
        self.assertIn("usg list", message)
        self.assertTrue(message.endswith(f"The end of its output: {error}"))

    def test_long_usg_output_keeps_its_last_lines(self):
        progress = [f"Checking rule {number} of 600" for number in range(600)]
        error = "Error: cannot write the results file"
        message = self.message({"rc": 1, "stdout_lines": progress, "stderr_lines": [error]})
        output = message.split("The end of its output: ", 1)[1]
        self.assertEqual(output, " ".join(progress[-9:] + [error]))
        # One very long line is still cut to its last 800 characters.
        message = self.message({"rc": 1, "stdout_lines": ["x" * 5000], "stderr_lines": [error]})
        output = message.split("The end of its output: ", 1)[1]
        self.assertEqual(len(output), 800)
        self.assertTrue(output.endswith(error))

    def test_silent_usg_and_the_oscap_scans_still_explain_themselves(self):
        silent = self.message({"rc": 2, "stdout_lines": [], "stderr_lines": []})
        self.assertTrue(silent.endswith("The end of its output: none"))
        # On Enterprise Linux and with a local content file the usg task was skipped.
        skipped = self.message({"changed": False, "skipped": True, "skip_reason": "Conditional result was False"})
        self.assertEqual(skipped, "The vendor scanner produced no results on lab-ubuntu. "
                                  "Rerun with -v to see the scanner output.")


def render(expression, **variables):
    """Render a playbook expression with the Ansible filters and tests the STIG tasks use."""
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters.update({
        "from_json": json.loads, "basename": os.path.basename, "dirname": os.path.dirname,
        "regex_replace": lambda value, pattern, replacement: re.sub(pattern, replacement, value)})
    environment.tests.update({"match": lambda value, pattern: re.match(pattern, value) is not None,
                              "abs": os.path.isabs})
    return environment.from_string(expression).render(**variables)


SCAN = "playbooks/tasks/stig_scan.yml"
STIG_PROFILE = "xccdf_org.ssgproject.content_profile_stig"


def scan_task(prefix):
    return next(task for task in walk(tasks(SCAN)) if task.get("name", "").startswith(prefix))


class StigMessageTests(unittest.TestCase):
    def test_no_message_carries_a_folded_line_break(self):
        """In a folded YAML scalar a more-indented line keeps its line break, which would show in the job output."""
        def strings(node, key=""):
            if isinstance(node, dict):
                for name, value in node.items():
                    yield from strings(value, name)
            elif isinstance(node, list):
                for value in node:
                    yield from strings(value, key)
            elif isinstance(node, str) and key in ("msg", "fail_msg"):
                yield node

        for path in (SCAN, *STIG_PLAYBOOKS):
            for text in strings(tasks(path)):
                outside = re.sub(r"\{\{.*?\}\}", "", text.strip(), flags=re.S)
                with self.subTest(path=path, text=text[:50]):
                    self.assertNotIn("\n", outside)


class ContentFolderTests(unittest.TestCase):
    """stig_content_file may name the system's content folder, which then holds exactly one DISA benchmark."""

    PROFILE = "xccdf_mil.disa.stig_profile_MAC-1_Classified"

    def verdict(self, content_file, stat, found=None, profile=PROFILE):
        task = scan_task("Refuse a missing file, a placeholder or an incomplete profile ID")
        variables = {"stig_content_file": content_file, "stig_content_profile": profile, "stig_content_stat": {"stat": stat},
                     "stig_content_found": {"files": [{"path": f"/opt/ansible-lab/{content_file}/{name}"}
                                                      for name in found]} if found is not None else {"skipped": True}}
        for name in ("stig_content_names", "stig_content_is_folder", "stig_content_profile_problem", "stig_content_problem"):
            variables[name] = render(task["vars"][name], **variables)
        accepted = all(render(condition if "{{" in condition else "{{ " + condition + " }}", **variables)
                       for condition in task["ansible.builtin.assert"]["that"])
        return accepted, render(task["ansible.builtin.assert"]["fail_msg"], **variables)

    def test_a_file_is_accepted_as_before(self):
        accepted, _message = self.verdict("content/rhel/9/U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml",
                                          {"exists": True, "isreg": True, "isdir": False})
        self.assertTrue(accepted)
        accepted, message = self.verdict("content/rhel/9/missing.xml", {"exists": False})
        self.assertFalse(accepted)
        self.assertTrue(message.startswith("There is no file content/rhel/9/missing.xml in the lab folder yet. Copy an XML"))

    def test_a_folder_stands_for_the_one_benchmark_in_it(self):
        folder = {"exists": True, "isreg": False, "isdir": True}
        accepted, _message = self.verdict("content/rhel/9", folder, ["U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml"])
        self.assertTrue(accepted)
        accepted, message = self.verdict("content/rhel/9", folder, [])
        self.assertFalse(accepted)
        self.assertTrue(message.startswith("The folder content/rhel/9 holds no DISA benchmark, "
                                           "a file whose name ends in _Benchmark.xml. Copy an XML"))
        accepted, message = self.verdict("content/rhel/9", folder, ["U_RHEL_9_V2R9_STIG_SCAP_1-3_Benchmark.xml",
                                                                   "U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml"])
        self.assertFalse(accepted)
        self.assertIn("holds 2 DISA benchmarks (U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml, "
                      "U_RHEL_9_V2R9_STIG_SCAP_1-3_Benchmark.xml); keep the one to scan with. Copy an XML", message)

    def test_a_short_profile_id_is_named_as_the_problem_not_the_folder(self):
        folder = {"exists": True, "isreg": False, "isdir": True}
        for content_file, stat, found in (("content/rhel/9", folder, ["U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml"]),
                                          ("content/rhel/9/U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml",
                                           {"exists": True, "isreg": True, "isdir": False}, None)):
            with self.subTest(content_file=content_file):
                accepted, message = self.verdict(content_file, stat, found, profile="MAC-1_Classified")
                self.assertFalse(accepted)
                self.assertTrue(message.startswith("stig_content_profile is not a full profile ID. Copy an XML"), message)
                self.assertNotIn("holds", message)

    def test_the_folder_is_searched_on_the_controller_for_disa_names_only(self):
        task = scan_task("List the DISA benchmarks in a content folder on the controller")
        self.assertEqual((task["delegate_to"], task["become"]), ("localhost", False))
        self.assertEqual(task["ansible.builtin.find"]["patterns"], "*_Benchmark.xml")
        self.assertEqual(task["when"], "stig_content_stat.stat.isdir | default(false)")
        chosen = scan_task("Scan with the one benchmark the content folder holds")
        self.assertEqual(chosen["when"], task["when"])
        self.assertEqual(chosen["ansible.builtin.set_fact"], {"stig_content_source": "{{ stig_content_found.files[0].path }}"})


class ExceptionsFileTests(unittest.TestCase):
    """An exceptions (XCCDF tailoring) file leaves rules out of the scan and of the fixes, and every run says so."""

    DESCRIBED = {"tailoring_id": "xccdf_site_tailoring_default", "benchmark": "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml",
                 "profile_id": STIG_PROFILE + "_site", "extends": STIG_PROFILE, "title": "Site exceptions",
                 "left_out": ["xccdf_org.ssgproject.content_rule_grub2_password",
                              "xccdf_org.ssgproject.content_group_partitions"],
                 "left_out_count": 2, "selected_count": 0, "values_set": 1, "sha256": "ab" * 32}

    def source(self, **variables):
        facts = scan_task("Note whether this scan uses a local SCAP content file or an exceptions file")
        return render(facts["ansible.builtin.set_fact"]["stig_tailoring_source"], ansible_search_path=["/opt/ansible-lab/playbooks/tasks"],
                      **{"stig_content_file": "", "stig_report_folder": "", "stig_tailoring_file": "", **variables})

    def test_the_named_file_wins_and_a_system_folder_has_a_default(self):
        self.assertEqual(self.source(stig_tailoring_file="content/site.xml", stig_report_folder="rhel/9"),
                         "/opt/ansible-lab/content/site.xml")
        self.assertEqual(self.source(stig_tailoring_file="/srv/site.xml"), "/srv/site.xml")
        self.assertEqual(self.source(stig_report_folder="rhel/9"),
                         "/opt/ansible-lab/content/rhel/9/tailoring.xml")
        # The default fits the vendor's content, so a DISA file scan needs the file named.
        self.assertEqual(self.source(stig_report_folder="rhel/9", stig_content_file="content/rhel/9"), "")
        # The shared playbooks run without a system folder.
        self.assertEqual(self.source(), "")

    def test_a_default_file_is_used_only_when_it_exists(self):
        look = scan_task("Look for an exceptions file on the controller")
        self.assertEqual((look["delegate_to"], look["become"], look["when"]),
                         ("localhost", False, "stig_tailoring_source | length > 0"))
        expression = scan_task("Note whether this scan uses an exceptions file")["ansible.builtin.set_fact"]["stig_tailored"]
        for named_file, stat, expected in (("content/site.xml", {"stat": {"exists": False}}, True),
                                           ("", {"stat": {"exists": True}}, True),
                                           ("", {"stat": {"exists": False}}, False),
                                           ("", {"skipped": True}, False)):
            with self.subTest(named_file=named_file, stat=stat):
                self.assertIs(render(expression, stig_tailoring_file=named_file, stig_tailoring_stat=stat), expected)

    def verdict(self, read, family="RedHat", local_content=False, usg_profile="disa_stig",
                content_profile="xccdf_mil.disa.stig_profile_MAC-1_Classified"):
        task = scan_task("Refuse an exceptions file that cannot be read or extends another profile")
        variables = {"stig_tailoring_read": read, "stig_local_content": local_content, "stig_profile_el": STIG_PROFILE,
                     "stig_usg_profile": usg_profile, "stig_content_profile": content_profile,
                     "ansible_facts": {"os_family": family}, "inventory_hostname": "lab-rhel",
                     "stig_tailoring_source": "/opt/ansible-lab/content/rhel/9/tailoring.xml"}
        for name in ("stig_tailoring_seen", "stig_tailoring_base", "stig_tailoring_error", "stig_tailoring_id_ok",
                     "stig_tailoring_problem"):
            variables[name] = render(task["vars"][name], **variables)
        # Ansible evaluates the conditions in order and stops at the first false one.
        accepted = all(render("{{ " + condition + " }}", **variables) for condition in task["ansible.builtin.assert"]["that"])
        return accepted, render(task["ansible.builtin.assert"]["fail_msg"], **variables)

    def read(self, **changes):
        return {"rc": 0, "stdout": json.dumps(dict(self.DESCRIBED, **changes)), "stderr": ""}

    def test_a_file_that_extends_the_runs_profile_is_accepted(self):
        self.assertTrue(self.verdict(self.read())[0])
        # Ubuntu's usg calls its STIG profile disa_stig, stig or stig-v1r1; all three are the same profile ID.
        for usg_profile in ("disa_stig", "stig", "stig-v1r1"):
            with self.subTest(usg_profile=usg_profile):
                self.assertTrue(self.verdict(self.read(), family="Debian", usg_profile=usg_profile)[0])
        # With a DISA file, the base is the profile chosen for that file.
        disa = self.read(extends="xccdf_mil.disa.stig_profile_MAC-1_Classified",
                         profile_id="xccdf_mil.disa.stig_profile_MAC-1_Classified_site")
        self.assertTrue(self.verdict(disa, local_content=True)[0])

    def test_a_file_for_another_profile_cannot_replace_the_baseline(self):
        other = "xccdf_org.ssgproject.content_profile_cis"
        for arguments in ({"family": "RedHat"}, {"family": "Debian"}, {"family": "RedHat", "local_content": True}):
            with self.subTest(**arguments):
                accepted, message = self.verdict(self.read(extends=other), **arguments)
                self.assertFalse(accepted)
                self.assertIn(f"Its profile {STIG_PROFILE}_site extends {other}, and this run scans with ", message)
                self.assertIn("Nothing was scanned or changed.", message)

    def test_on_ubuntu_a_file_is_checked_against_the_stig_profile_or_refused(self):
        # usg takes the profile from the file, so a file must never decide the baseline by itself.
        cis = "xccdf_org.ssgproject.content_profile_cis_level1_server"
        # A file for another baseline under any of the STIG profile's names.
        for usg_profile in ("disa_stig", "stig", "stig-v1r1"):
            with self.subTest(usg_profile=usg_profile):
                accepted, message = self.verdict(self.read(extends=cis), family="Debian", usg_profile=usg_profile)
                self.assertFalse(accepted)
                self.assertIn(f"extends {cis}, and this run scans with {STIG_PROFILE}.", message)
        # Another usg profile: the base is unknown, so neither a STIG file nor a matching one is used.
        for extends in (STIG_PROFILE, cis):
            with self.subTest(extends=extends):
                accepted, message = self.verdict(self.read(extends=extends), family="Debian",
                                                 usg_profile="cis_level1_server-v1.0.0")
                self.assertFalse(accepted)
                self.assertIn("This run uses the Ubuntu Security Guide profile cis_level1_server-v1.0.0, and an exceptions "
                              "file is only checked against its STIG profile, disa_stig. It must be", message)

    def test_a_profile_id_that_is_no_xccdf_id_is_named_as_the_problem(self):
        accepted, message = self.verdict(self.read(profile_id="site_exceptions"))
        self.assertFalse(accepted)
        self.assertIn("Its profile ID site_exceptions is not a full XCCDF profile ID. It must be", message)
        self.assertNotIn("this run scans with", message)

    def test_an_unreadable_file_is_refused_with_the_readers_words(self):
        error = "Cannot read the tailoring file: Expected one Profile in the tailoring file, found 2\n"
        accepted, message = self.verdict({"rc": 1, "stdout": "", "stderr": error})
        self.assertFalse(accepted)
        closing = (" It must be an XCCDF tailoring file with one profile that extends the profile this run uses; "
                   "chapter 9 shows how to make one with the vendor's own tool. Nothing was scanned or changed.")
        self.assertEqual(message, "The exceptions file tailoring.xml cannot be used on lab-rhel. " + error.strip() + "." + closing)
        # The reader's sentence ends once: an error that brings its own period gets no second one.
        missing = "Cannot read the tailoring file: [Errno 2] No such file or directory: '/opt/ansible-lab/content/none.xml'"
        for stderr in (missing, missing + ".\n"):
            _accepted, message = self.verdict({"rc": 1, "stdout": "", "stderr": stderr})
            self.assertIn("none.xml'." + closing, message)
            self.assertNotIn("..", message.replace("playbooks/../", ""))
        # A profile ID that could not be an oscap argument is refused as well.
        self.assertFalse(self.verdict(self.read(profile_id="stig; reboot"))[0])

    def test_every_run_names_the_file_its_hash_and_what_it_leaves_out(self):
        task = scan_task("Name the exceptions file and what it leaves out")
        variables = {"inventory_hostname": "lab-rhel", "stig_tailoring": self.DESCRIBED,
                     "stig_tailoring_source": "/opt/ansible-lab/content/rhel/9/tailoring.xml"}
        def message(described):
            variables["stig_tailoring"] = described
            for name in ("stig_tailoring_left_out", "stig_tailoring_refined", "stig_tailoring_refined_note"):
                variables[name] = render(task["vars"][name], **variables)
            return render(task["ansible.builtin.debug"]["msg"], **variables)

        self.assertEqual(message(self.DESCRIBED),
                         f"lab-rhel: exceptions file tailoring.xml (SHA-256 {'ab' * 32}) extends {STIG_PROFILE}, "
                         "leaves out 2 rule(s) or group(s), sets 1 value(s) and refines 0 rule(s). Left out: "
                         "grub2_password, partitions. What it leaves out is neither scanned nor fixed in this run; "
                         "record who accepted each exception.")
        many = dict(self.DESCRIBED, left_out=[f"xccdf_org.ssgproject.content_rule_r{n}" for n in range(45)], left_out_count=45)
        self.assertIn("r39, and 5 more. What it leaves out", message(many))
        # Only the benchmark's prefix is cut: a name that contains _rule_ or _group_ stays whole.
        odd = dict(self.DESCRIBED, left_out_count=3,
                   left_out=["xccdf_org.ssgproject.content_rule_group_unique_id",
                             "xccdf_org.ssgproject.content_rule_gid_passwd_group_same",
                             "xccdf_mil.disa.stig_rule_SV-258155r1045300_rule"])
        self.assertIn("Left out: group_unique_id, gid_passwd_group_same, SV-258155r1045300_rule. What", message(odd))
        # A rule whose role, severity or weight the file changes is named too.
        refined = dict(self.DESCRIBED, rules_refined=["xccdf_org.ssgproject.content_rule_sshd_set_idle_timeout"],
                       rules_refined_count=1)
        self.assertIn("sets 1 value(s) and refines 1 rule(s). Left out: grub2_password, partitions. Refined, with another "
                      "role, severity or weight than the profile gives: sshd_set_idle_timeout. What it leaves out",
                      message(refined))

    def commands(self, tailored, local_content=False, controller=False):
        variables = {"stig_tailored": tailored, "stig_tailoring_remote": "/var/log/stig-scans/S/tailoring.xml" if tailored else "",
                     "stig_tailoring": self.DESCRIBED, "stig_local_content": local_content, "stig_profile_el": STIG_PROFILE,
                     "stig_content_profile": "xccdf_mil.disa.stig_profile_MAC-1_Classified", "stig_usg_profile": "disa_stig",
                     "stig_fetch_remote_resources": False, "stig_remote_dir": "/var/log/stig-scans/S", "stig_phase": "audit",
                     "stig_datastream": "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml"}
        chosen = scan_task("Choose the profile this run scans with")["ansible.builtin.set_fact"]
        variables["stig_scan_profile"] = render(chosen["stig_scan_profile"], **variables)
        self.assertEqual(render(chosen["stig_tailoring_remote"], **variables), variables["stig_tailoring_remote"])
        apply = tasks("playbooks/stig/apply.yml")[0]["tasks"]
        # The Ubuntu fix builds its command from two task variables; a target that is not the controller
        # gets the plain usg command.
        usg_fix = named(apply, "Apply the vendor remediation on Ubuntu")
        variables.update(stig_is_controller=controller, stig_keep_ssh_client=usg_fix["vars"]["stig_keep_ssh_client"],
                         stig_usg_fix=render(usg_fix["vars"]["stig_usg_fix"], **variables))
        return {name: render(task["ansible.builtin.command"]["argv"], **variables) for name, task in (
            ("el", scan_task("Scan Enterprise Linux against the vendor STIG profile")),
            ("usg", scan_task("Scan Ubuntu with the Ubuntu Security Guide STIG profile")),
            ("local", scan_task("Scan against the profile in the local content file")),
            ("el_fix", named(apply, "Apply the vendor remediation on Enterprise Linux")),
            ("usg_fix", named(apply, "Apply the vendor remediation on Ubuntu")))}

    def test_without_an_exceptions_file_the_commands_are_the_earlier_ones(self):
        commands = self.commands(False)
        stream, folder = "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml", "/var/log/stig-scans/S"
        self.assertEqual(commands["el"], ["oscap", "xccdf", "eval", "--profile", STIG_PROFILE, "--results",
                                          f"{folder}/audit.xml", "--report", f"{folder}/audit.html", stream])
        self.assertEqual(commands["usg"], ["usg", "audit", "disa_stig", "--results-file", f"{folder}/audit.xml",
                                           "--html-file", f"{folder}/audit.html"])
        self.assertEqual(commands["el_fix"], ["oscap", "xccdf", "eval", "--remediate", "--profile", STIG_PROFILE, "--results",
                                              f"{folder}/remediate.xml", "--report", f"{folder}/remediate.html", stream])
        self.assertEqual(commands["usg_fix"], ["usg", "fix", "disa_stig"])
        self.assertEqual(self.commands(False, local_content=True)["local"],
                         ["oscap", "xccdf", "eval", "--profile", "xccdf_mil.disa.stig_profile_MAC-1_Classified", "--results",
                          f"{folder}/audit.xml", "--report", f"{folder}/audit.html", f"{folder}/content.xml"])

    def test_on_its_own_controller_the_ubuntu_fix_gives_the_ssh_client_its_files_back(self):
        # usg works with umask 077 and leaves the SSH client's files for root only, which ends ssh for the
        # semaphore account. The fix and the repair are one command: no later task could connect.
        for tailored, tail in ((False, ["usg", "fix", "disa_stig"]),
                               (True, ["usg", "fix", "--tailoring-file", "/var/log/stig-scans/S/tailoring.xml"])):
            argv = self.commands(tailored, controller=True)["usg_fix"]
            self.assertEqual(argv[:2] + argv[3:], ["/bin/sh", "-c", "usg-fix"] + tail)
        script = argv[2]
        self.assertIn("/etc/ssh/ssh_config.d", script)
        with tempfile.TemporaryDirectory() as work:
            folder, binaries = Path(work, "ssh_config.d"), Path(work, "bin")
            folder.mkdir()
            binaries.mkdir()
            (folder / "50-site.conf").write_text("Host *\n")
            (folder / "50-site.conf").chmod(0o644)
            (folder / "notes.txt").write_text("not a configuration file\n")
            (folder / "notes.txt").chmod(0o600)
            # A stand-in usg: it writes its files as usg does and ends with a status of its own.
            (binaries / "usg").write_text(f"#!/bin/sh\necho \"usg $*\"\numask 077\necho 'Host *' > {folder}/00-cipher-list.conf\n"
                                          f"echo 'Host *' > {folder}/00-mac-list.conf\nexit 3\n")
            (binaries / "usg").chmod(0o755)
            result = subprocess.run(["/bin/sh", "-c", script.replace("/etc/ssh/ssh_config.d", str(folder)), *argv[3:]],
                                    capture_output=True, text=True, timeout=30,
                                    env={"PATH": f"{binaries}{os.pathsep}/usr/bin:/bin"})
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (3, "usg fix --tailoring-file /var/log/stig-scans/S/tailoring.xml\n", ""))
            modes = {path.name: oct(path.stat().st_mode & 0o777) for path in folder.iterdir()}
            self.assertEqual(modes, {"00-cipher-list.conf": "0o644", "00-mac-list.conf": "0o644",
                                     "50-site.conf": "0o644", "notes.txt": "0o600"})

    def test_with_one_every_scan_and_fix_uses_the_file_and_its_profile(self):
        commands = self.commands(True)
        remote, tailored = "/var/log/stig-scans/S/tailoring.xml", STIG_PROFILE + "_site"
        # oscap: the vendor's documented pair, --tailoring-file with the file's profile as --profile.
        for name in ("el", "el_fix"):
            with self.subTest(command=name):
                argv = commands[name]
                self.assertEqual(argv[argv.index("--tailoring-file") + 1], remote)
                self.assertEqual(argv[argv.index("--profile") + 1], tailored)
                self.assertNotIn(STIG_PROFILE, argv)
        # usg: the file instead of a profile name, as Canonical documents it.
        self.assertEqual(commands["usg"][:4], ["usg", "audit", "--tailoring-file", remote])
        self.assertNotIn("disa_stig", commands["usg"])
        self.assertEqual(commands["usg_fix"], ["usg", "fix", "--tailoring-file", remote])
        local = self.commands(True, local_content=True)["local"]
        self.assertEqual(local[3:7], ["--tailoring-file", remote, "--profile", tailored])

    def test_the_file_reaches_the_target_root_only_and_the_summary_reads_the_controllers_copy(self):
        copy = scan_task("Copy the exceptions file to the target")
        self.assertEqual(copy["when"], "stig_tailored")
        self.assertEqual(copy["ansible.builtin.copy"], {"src": "{{ stig_tailoring_source }}", "dest": "{{ stig_tailoring_remote }}",
                                                        "owner": "root", "group": "root", "mode": "0600"})
        summarize = scan_task("Summarize the fetched XCCDF result on the controller")
        variables = {"ansible_search_path": ["/opt/ansible-lab/playbooks/tasks"], "stig_fetch_dir": "/srv/u/stig-reports/rhel/9/S",
                     "inventory_hostname": "lab-rhel", "stig_phase": "before", "stig_tailoring_source": "/opt/t.xml"}
        base = ["/usr/bin/python3", "/opt/ansible-lab/scripts/summarize_xccdf.py",
                "/srv/u/stig-reports/rhel/9/S/lab-rhel/before.xml", "--findings",
                "/srv/u/stig-reports/rhel/9/S/lab-rhel/before-findings.csv"]
        argv = summarize["ansible.builtin.command"]["argv"]
        self.assertEqual(render(argv, stig_tailored=False, **variables), base)
        self.assertEqual(render(argv, stig_tailored=True, **variables), base + ["--tailoring", "/opt/t.xml"])

    def test_both_playbooks_take_the_variable_and_apply_fixes_after_the_first_scan(self):
        for playbook in STIG_PLAYBOOKS:
            with self.subTest(playbook=playbook):
                self.assertEqual(tasks(playbook)[0]["vars"]["stig_tailoring_file"], "")
        names = [task["name"] for task in tasks("playbooks/stig/apply.yml")[0]["tasks"]]
        # The scan before the fixes checks the file, chooses its profile and copies it to the target.
        self.assertLess(names.index("Record the posture before remediation"),
                        names.index("Apply the vendor remediation on Enterprise Linux"))


class ReleaseAndFindingsLineTests(unittest.TestCase):
    """Each scan says which STIG release its content follows and lists the failing rules by category."""

    SUMMARY = {"content": {"line": "STIG release V2R9: profile 'DISA STIG for Red Hat Enterprise Linux 9' in 'Guide' 0.1.82, "
                                   "file /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml, scanner cpe:/a:redhat:openscap:1.3.14"},
               "failed_by_category": {"CAT I": 2, "CAT II": 9, "CAT III": 3, "unrated": 1},
               "failed_cat_i": ["RHEL-09-212010 (grub2_password): Set Boot Loader Password in grub2",
                                "RHEL-09-671010 (sysctl_crypto_fips_enabled): Set kernel parameter"],
               "failed_cat_i_ids": ["RHEL-09-212010", "RHEL-09-671010"],
               "findings_file": "/srv/u/stig-reports/rhel/9/S/lab-rhel/audit-findings.csv",
               "has_scanner_errors_or_unknowns": False}

    def line(self, prefix, summary=None, **variables):
        task = scan_task(prefix)
        stdout = json.dumps(self.SUMMARY if summary is None else summary)
        variables = {"inventory_hostname": "lab-rhel", "stig_summary": {"rc": 0, "stdout": stdout}, "stig_local_content": False,
                     "stig_tailored": False, **variables}
        if not all(render("{{ " + condition + " }}", **variables) for condition in task["when"]):
            return False, ""
        for name, expression in task["vars"].items():
            variables[name] = render(expression, **variables)
        return True, render(task["ansible.builtin.debug"]["msg"], **variables)

    def test_the_release_line_names_content_and_exceptions(self):
        shown, text = self.line("Say which STIG release and content the scan measured")
        self.assertTrue(shown)
        self.assertEqual(text, "lab-rhel: " + self.SUMMARY["content"]["line"] + "; no exceptions file. Compare the release "
                               "with the one DISA lists for this system before you report results.")
        _shown, text = self.line("Say which STIG release and content the scan measured", stig_tailored=True,
                                 stig_tailoring={"left_out_count": 3}, stig_tailoring_source="/opt/lab/content/rhel/9/tailoring.xml")
        self.assertIn("; with exceptions file tailoring.xml, which leaves out 3 rule(s) or group(s). Compare", text)
        _shown, text = self.line("Say which STIG release and content the scan measured", stig_local_content=True,
                                 stig_content_source="/opt/lab/content/rhel/9/U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml")
        self.assertIn("1.3.14, copied from U_RHEL_9_V2R10_STIG_SCAP_1-3_Benchmark.xml; no exceptions file.", text)

    def test_the_failing_rules_line_counts_categories_and_names_cat_i(self):
        shown, text = self.line("List the failing rules by severity category")
        self.assertTrue(shown)
        self.assertEqual(text, "lab-rhel: failing rules by DISA category: CAT I (high) 2, CAT II (medium) 9, CAT III (low) 3, "
                               "without a category 1. CAT I: RHEL-09-212010, RHEL-09-671010. Every failing, unchecked or "
                               "errored rule is in /srv/u/stig-reports/rhel/9/S/lab-rhel/audit-findings.csv with its "
                               "category, STIG ID and rule ID.")
        clean = dict(self.SUMMARY, failed_by_category={"CAT I": 0, "CAT II": 0, "CAT III": 0, "unrated": 0},
                     failed_cat_i=[], failed_cat_i_ids=[])
        self.assertIn("without a category 0. Every failing", self.line("List the failing rules by severity category", clean)[1])

    def test_a_summary_without_the_new_keys_shows_neither_line(self):
        # A summary that lacks the release and the categories still reports its counts, without the two lines.
        earlier = {"outcome_instances": {"pass": 1}, "has_scanner_errors_or_unknowns": False}
        for prefix in ("Say which STIG release and content the scan measured", "List the failing rules by severity category"):
            with self.subTest(task=prefix):
                self.assertFalse(self.line(prefix, earlier)[0])
        unavailable = {"rc": 1, "stdout": "", "stderr": "Cannot summarize assessment"}
        task = scan_task("List the failing rules by severity category")
        self.assertFalse(all(render("{{ " + condition + " }}", stig_summary=unavailable) for condition in task["when"]))


class PerSystemPlaybookTests(unittest.TestCase):
    """playbooks/stig/<system>/<version>/ hold thin wrappers around the shared STIG playbooks."""

    SAMPLE_FACTS = {"RedHat-9": ("RedHat", "9.8", "9"), "AlmaLinux-9": ("AlmaLinux", "9.8", "9"),
                    "Rocky-9": ("Rocky", "9.6", "9"), "Ubuntu-24.04": ("Ubuntu", "24.04", "24")}

    def os_key(self, playbook, facts):
        play = tasks(playbook)[0]
        task = named(play["pre_tasks"], "Name this host's system")
        distribution, version, major = facts
        return native(task["ansible.builtin.set_fact"]["stig_os_key"], ansible_facts={
            "distribution": distribution, "distribution_version": version,
            "distribution_major_version": major}).strip()

    def test_each_seeded_system_has_an_audit_and_an_apply_wrapper(self):
        systems = load("seed-semaphore").STIG_SYSTEMS
        found = sorted(str(p.relative_to(ROOT / "playbooks" / "stig")) for p in (ROOT / "playbooks/stig").rglob("*")
                       if p.is_file())
        # The two shared playbooks, and one pair of thin ones per system and version.
        self.assertEqual(found, sorted(["apply.yml", "audit.yml"] + [f"{folder}/{kind}.yml" for _l, folder, _g, _f in systems
                                                                    for kind in ("apply", "audit")]))
        scopes = set()
        for _label, folder, _group, _file in systems:
            for kind, shared in (("audit", "audit.yml"), ("apply", "apply.yml")):
                with self.subTest(playbook=f"{folder}/{kind}.yml"):
                    (entry,) = tasks(f"playbooks/stig/{folder}/{kind}.yml")
                    self.assertEqual(entry["ansible.builtin.import_playbook"], f"../../{shared}")
                    self.assertEqual(entry["vars"]["stig_report_folder"], folder)
                    scopes.add(entry["vars"]["stig_os_scope"])
        self.assertEqual(scopes, set(self.SAMPLE_FACTS))

    def test_the_shared_playbooks_name_each_system_as_its_wrapper_does(self):
        for playbook in STIG_PLAYBOOKS:
            play = tasks(playbook)[0]
            self.assertEqual((play["vars"]["stig_os_scope"], play["vars"]["stig_report_folder"]), ("", ""))
            names = [t["name"] for t in play["pre_tasks"]]
            self.assertLess(names.index("Check scope and supported operating system"),
                            names.index("Name this host's system the way the per-system playbooks do"))
            for scope, facts in self.SAMPLE_FACTS.items():
                with self.subTest(playbook=playbook, scope=scope):
                    self.assertEqual(self.os_key(playbook, facts), scope)

    def test_the_system_names_in_messages_match_the_seeded_templates(self):
        systems = yaml.safe_load((ROOT / "playbooks/vars/stig_systems.yml").read_text())["stig_systems"]
        seeded = load("seed-semaphore").STIG_SYSTEMS
        wrappers = {tasks(f"playbooks/stig/{folder}/audit.yml")[0]["vars"]["stig_os_scope"]: (label, folder)
                    for label, folder, _group, _file in seeded}
        self.assertEqual({key: (value["label"], value["folder"]) for key, value in systems.items()}, wrappers)
        for playbook in STIG_PLAYBOOKS:
            self.assertEqual(tasks(playbook)[0]["vars_files"], ["../vars/stig_systems.yml"])

    def test_an_audit_with_no_host_of_its_system_stops_with_an_explanation(self):
        audit = tasks("playbooks/stig/audit.yml")[0]["pre_tasks"]
        stop = named(audit, "Stop when no host in the run has the system this playbook audits")
        self.assertIn("select('equalto', stig_os_scope)", " ".join(stop["when"]))
        names = [t["name"] for t in audit]
        self.assertLess(names.index(stop["name"]), next(i for i, t in enumerate(audit)
                                                        if t.get("ansible.builtin.meta") == "end_host"))

    def test_audit_skips_and_apply_refuses_another_system(self):
        audit = tasks("playbooks/stig/audit.yml")[0]["pre_tasks"]
        end = next(t for t in audit if t.get("ansible.builtin.meta") == "end_host")
        self.assertEqual(end["when"], "stig_os_scope | length > 0 and stig_os_key != stig_os_scope")
        apply = tasks("playbooks/stig/apply.yml")[0]["pre_tasks"]
        refusal = named(apply, "Refuse a host that another system's playbook covers")
        condition = refusal["ansible.builtin.assert"]["that"][0]
        for scope, key, accepted in (("", "Rocky-9", True), ("RedHat-9", "RedHat-9", True),
                                     ("RedHat-9", "AlmaLinux-9", False)):
            with self.subTest(scope=scope, key=key):
                self.assertIs(native("{{ " + condition + " }}", stig_os_scope=scope, stig_os_key=key), accepted)
        names = [t["name"] for t in apply]
        self.assertLess(names.index(refusal["name"]), next(i for i, t in enumerate(apply)
                                                           if "stig_confirm" in json.dumps(t)))

    def test_reports_of_a_per_system_run_land_in_its_folder(self):
        for playbook in STIG_PLAYBOOKS:
            expression = tasks(playbook)[0]["vars"]["stig_fetch_dir"]
            with self.subTest(playbook=playbook):
                for folder, expected in (("rhel/9", "/srv/u/stig-reports/rhel/9/S"), ("", "/srv/u/stig-reports/S")):
                    rendered = jinja2.Environment().from_string(expression).render(
                        lookup=lambda _kind, _name: "/srv/u", stig_report_folder=folder, stig_stamp="S")
                    self.assertEqual(rendered.strip(), expected)

    def test_every_host_of_one_run_shares_its_report_folder(self):
        def now(utc=False, fmt=None):
            self.assertIs(utc, True)
            return datetime.datetime(2026, 10, 19, 14, 25, 30).strftime(fmt)

        for playbook in STIG_PLAYBOOKS:
            play = tasks(playbook)[0]
            with self.subTest(playbook=playbook):
                # A play variable is templated for each host from its own facts and clock.
                self.assertNotIn("stig_stamp", play["vars"])
                self.assertIn("{{ stig_stamp }}", play["vars"]["stig_remote_dir"])
                stamp = named(play["pre_tasks"], "Use one report folder for the whole run")
                # run_once sets the fact on every host of the batch, and tags keep it in tagged runs.
                self.assertIs(stamp["run_once"], True)
                self.assertIn("always", stamp["tags"])
                # It must not run before the preflight gathers facts; see FactCacheTests.
                names = [t["name"] for t in play["pre_tasks"]]
                preflight = names.index("Check scope and supported operating system")
                self.assertGreater(names.index(stamp["name"]), preflight)
                expression = stamp["ansible.builtin.set_fact"]["stig_stamp"]
                rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(expression).render(now=now)
                self.assertEqual(rendered, "20261019T142530Z")


class FactCacheTests(unittest.TestCase):
    """In ansible-core 2.21 a run_once task, even a debug, stores one shared object as the fact
    cache of every host that has none yet. Those hosts then share the facts the preflight
    gathers, and each sees the system of whichever host gathered last."""

    def test_no_run_once_task_runs_before_the_hosts_have_facts(self):
        checked = 0
        for playbook in FEATURE_PLAYBOOKS:
            for play in yaml.safe_load(playbook.read_text()):
                gathered = play.get("gather_facts", True)
                for task in walk(play.get("pre_tasks", []) + play.get("tasks", [])):
                    if task.get("run_once"):
                        checked += 1
                        with self.subTest(playbook=playbook.name, task=task["name"]):
                            self.assertTrue(gathered, "this run_once task runs before fact gathering")
                    gathered = gathered or "ansible.builtin.setup" in task
        self.assertGreaterEqual(checked, len(STIG_PLAYBOOKS))


class PrivilegeTests(unittest.TestCase):
    """Only the preflight's two reads, and tasks on the controller, run without sudo."""

    PROBES = ("Gather operating-system facts", "Verify the operating system's package bindings are ready")
    SUDO_PLAYBOOKS = ("playbooks/baseline/baseline.yml", "playbooks/examples/users.yml", "playbooks/examples/webserver.yml",
                      "playbooks/patching/patch.yml", "playbooks/operations/reboot.yml") + STIG_PLAYBOOKS
    # Actions that run on the controller without opening a connection to the host.
    CONTROLLER_ACTIONS = {"assert", "debug", "fail", "include_vars", "meta", "set_fact"}

    def test_the_preflight_reads_run_without_sudo(self):
        preflight = tasks("playbooks/tasks/preflight.yml")
        for name in self.PROBES:
            with self.subTest(task=name):
                self.assertIs(named(preflight, name)["become"], False)

    def test_stig_runs_use_no_sudo_before_choosing_their_hosts(self):
        # A host of another system is skipped or refused at the decision, before any sudo password
        # reaches it; a wrong one counts toward faillock on a STIG-hardened host.
        for playbook, decision in (("playbooks/stig/audit.yml", "Leave hosts of other systems to their own playbook"),
                                   ("playbooks/stig/apply.yml", "Refuse a host that another system's playbook covers")):
            play = tasks(playbook)[0]
            self.assertIs(play["gather_facts"], False)
            names = [t["name"] for t in play["pre_tasks"]]
            for task in walk(play["pre_tasks"][:names.index(decision)]):
                action = next(key for key in task if key.startswith("ansible.builtin."))
                with self.subTest(playbook=playbook, task=task["name"]):
                    self.assertTrue(action.removeprefix("ansible.builtin.") in self.CONTROLLER_ACTIONS
                                    or task.get("become") is False)

    def test_every_other_task_on_a_target_keeps_the_plays_sudo(self):
        for playbook in self.SUDO_PLAYBOOKS:
            play = tasks(playbook)[0]
            self.assertIs(play["become"], True)
            for task in walk(play.get("pre_tasks", []) + play.get("tasks", []) + play.get("handlers", [])):
                if task.get("become") is False:
                    with self.subTest(playbook=playbook, task=task["name"]):
                        self.assertTrue(task["name"] in self.PROBES or task.get("delegate_to") == "localhost")


    def test_no_option_is_split_by_a_comma_in_a_bracketed_list(self):
        # YAML reads [df, --output=size,used] as three items. Every option that takes a
        # comma-separated value must therefore arrive whole, and no item may be a bare word
        # that only makes sense as the rest of such a value.
        for name in ("report.yml", "reboot.yml"):
            for play in tasks(f"playbooks/{name}"):
                for task in play.get("pre_tasks", []) + play.get("tasks", []) + play.get("post_tasks", []):
                    command = task.get("ansible.builtin.command")
                    if not isinstance(command, dict) or "argv" not in command:
                        continue
                    with self.subTest(playbook=name, task=task["name"]):
                        self.assertTrue(all(isinstance(item, str) for item in command["argv"]), command["argv"])
                        if command["argv"][0] == "df":
                            self.assertEqual(command["argv"], ["df", "--output=size,used,avail,pcent", "--block-size=1M", "/"])

    def test_the_health_report_never_asks_for_sudo(self):
        # It runs right after Ping, before Semaphore holds a sudo password.
        play = tasks("playbooks/operations/report.yml")[0]
        self.assertIs(play["become"], False)
        for task in walk(play["pre_tasks"] + play["tasks"]):
            with self.subTest(task=task["name"]):
                self.assertNotEqual(task.get("become"), True)
                self.assertNotIn("become_user", task)


try:
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar, trust_as_template
except ImportError:  # CI and the gate install ansible-core; without it these tests are skipped.
    Templar = None


def trusted(value):
    """Mark playbook text as a template, as Ansible does for what it reads from a playbook."""
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, list):
        return [trusted(item) for item in value]
    if isinstance(value, dict):
        return {key: trusted(item) for key, item in value.items()}
    return value


def rendered(play, variables, value):
    """value as ansible-core renders it, with the play's variables worked out lazily from these.

    Ansible keeps the backslashes of a string literal in an expression, where plain Jinja
    would read escapes, so regular expressions are checked with its own templating.
    """
    # Registered results and extra variables take precedence over play variables, as in Ansible.
    templar = Templar(loader=DataLoader(), variables=dict(trusted(play["vars"]), **variables))
    return templar.template(trusted(value))


def encoded(text):
    return {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"}


def command(rc, *lines):
    return {"rc": rc, "stdout": "\n".join(lines), "stdout_lines": list(lines), "changed": False}


SKIPPED = {"changed": False, "skipped": True, "skip_reason": "Conditional result was False"}


@unittest.skipUnless(Templar, "needs ansible-core, as CI installs it")
class ReadOnlyOperationsTests(unittest.TestCase):
    """report.yml only reads, in check mode too, and reports instead of failing."""

    READS = {"ansible.builtin.slurp", "ansible.builtin.stat", "ansible.builtin.command", "ansible.builtin.setup"}
    CONTROLLER = {f"ansible.builtin.{action}" for action in PrivilegeTests.CONTROLLER_ACTIONS}

    def test_every_task_only_reads_and_reports_no_change_even_in_check_mode(self):
        play = tasks("playbooks/operations/report.yml")[0]
        probes_that_may_fail = set()
        for task in walk(play["pre_tasks"] + play["tasks"]):
            module = next(key for key in task if key.startswith("ansible.builtin."))
            with self.subTest(task=task["name"]):
                self.assertIn(module, self.READS | self.CONTROLLER)
                if module == "ansible.builtin.command":
                    self.assertIs(task["changed_when"], False)
                    # Commands are skipped in check mode unless told otherwise.
                    self.assertIs(task["check_mode"], False)
                    if task.get("failed_when") is False:
                        probes_that_may_fail.add(task["name"])
                self.assertNotIn("ignore_errors", task)
        # Only reading the root file system may fail the host; every other probe reports unknown.
        commands = {t["name"] for t in walk(play["tasks"]) if "ansible.builtin.command" in t}
        self.assertEqual(commands - probes_that_may_fail, {"Measure the root file system"})

    def report(self, facts, **registered):
        play = tasks("playbooks/operations/report.yml")[0]
        variables = dict(inventory_hostname=facts.pop("host"), ansible_facts=facts, **registered)
        summary = named(play["tasks"], "Summarize each host")["ansible.builtin.debug"]["msg"]
        verdict = named(play["tasks"], "Say whether each host needs attention")["ansible.builtin.debug"]["msg"]
        self.assertIsInstance(rendered(play, variables, "{{ report_attention }}"), list)
        return ([" ".join(line.split()) for line in rendered(play, variables, summary)],
                rendered(play, variables, verdict))

    UBUNTU = {"host": "lab-ubuntu", "distribution": "Ubuntu", "distribution_version": "24.04",
              "os_family": "Debian", "kernel": "6.8.0-88-generic"}
    ALMA = {"host": "lab-alma", "distribution": "AlmaLinux", "distribution_version": "9.6",
            "os_family": "RedHat", "kernel": "5.14.0-503.el9.x86_64"}

    def healthy(self, **changes):
        return dict({
            "report_uptime": encoded("93784.55 180000.10\n"),
            "report_meminfo": encoded("MemTotal:        4028000 kB\nMemFree:  100 kB\nMemAvailable:    3021000 kB\n"),
            "report_root_fs": command(0, "1M-blocks  Used Avail Use%", "    19940  4567 14340  25%"),
            "report_failed": command(0),
            "report_reboot_marker": {"changed": False, "stat": {"exists": False}},
            "report_kernels": SKIPPED,
            "report_clock": command(0, "NTP=yes", "NTPSynchronized=yes"),
            "report_apt": command(0, "NOTE: This is only a simulation!", "0 upgraded, 0 newly installed."),
            "report_dnf": SKIPPED,
        }, **changes)

    def test_a_healthy_host_is_ok(self):
        summary, verdict = self.report(dict(self.UBUNTU), **self.healthy())
        self.assertEqual(summary, [
            "lab-ubuntu: Ubuntu 24.04, kernel 6.8.0-88-generic, up 1 d 2 h 3 min",
            "Root file system: 25% used, 14340 MiB free of 19940 MiB. Memory: 25% used, 2950 MiB available of 3933 MiB.",
            "Failed systemd units: 0",
            "Reboot pending: no",
            "Time: synchronized",
            "Pending package updates: none"])
        self.assertEqual(verdict, "lab-ubuntu: OK")

    def test_everything_that_needs_attention_is_listed_on_one_line(self):
        units = ["● nfs.mount loaded failed failed NFS", "-.mount loaded failed failed Root"] + [
            f"unit{n}.service loaded failed failed Unit {n}" for n in range(5)]
        summary, verdict = self.report(dict(self.ALMA), **self.healthy(
            report_meminfo=encoded("MemTotal: 2048000 kB\nMemAvailable: 102400 kB\n"),
            report_root_fs=command(0, "1M-blocks  Used Avail Use%", "    19940 18943   997  95%"),
            report_failed=command(0, *units),
            report_reboot_marker=SKIPPED,
            report_kernels=command(0, "1730000000 5.14.0-570.el9.x86_64", "1727000000 5.14.0-503.el9.x86_64"),
            report_clock=command(0, "NTP=no", "NTPSynchronized=no"),
            report_apt=SKIPPED,
            report_dnf=command(0, "bash.x86_64", "kernel-core.x86_64", "bash.x86_64")))
        self.assertIn("Failed systemd units: 7: nfs.mount, -.mount, unit0.service, unit1.service, unit2.service, ...",
                      summary)
        self.assertIn("Reboot pending: yes (running 5.14.0-503.el9.x86_64, newest installed 5.14.0-570.el9.x86_64)",
                      summary)
        self.assertIn("Pending package updates: 2", summary)
        self.assertEqual(verdict, "lab-alma: needs attention: root file system 95% full; memory 95% used; "
                                  "7 failed systemd unit(s); reboot pending; clock not synchronized, time service "
                                  "inactive; 2 package update(s) pending")

    def test_probes_that_cannot_read_are_reported_not_failed(self):
        summary, verdict = self.report(dict(self.ALMA), **self.healthy(
            report_failed=command(1), report_reboot_marker=SKIPPED, report_kernels=command(1),
            report_clock=command(1), report_apt=SKIPPED, report_dnf=command(1)))
        self.assertIn("Failed systemd units: unknown, systemctl could not list them", summary)
        self.assertIn("Reboot pending: unknown", summary)
        self.assertIn("Time: unknown", summary)
        self.assertIn("Pending package updates: not checked; the local package data could not be read without sudo",
                      summary)
        # A count that could not be made is not a finding.
        self.assertEqual(verdict, "lab-alma: needs attention: failed systemd units could not be listed; reboot need "
                                  "unknown; time synchronization unknown")

    def test_the_running_newest_kernel_needs_no_reboot(self):
        summary, verdict = self.report(dict(self.ALMA, kernel="5.14.0-570.el9.x86_64"), **self.healthy(
            report_reboot_marker=SKIPPED, report_apt=SKIPPED,
            report_kernels=command(0, "1727000000 5.14.0-503.el9.x86_64", "1730000000 5.14.0-570.el9.x86_64"),
            report_dnf=command(0)))
        self.assertIn("Reboot pending: no", summary)
        self.assertEqual(verdict, "lab-alma: OK")

    def test_the_ubuntu_reboot_marker_counts(self):
        _summary, verdict = self.report(dict(self.UBUNTU), **self.healthy(
            report_reboot_marker={"changed": False, "stat": {"exists": True}},
            report_apt=command(0, "Inst libc6 [2.39-0ubuntu8.5] (2.39-0ubuntu8.6 Ubuntu:24.04/noble-updates [amd64])",
                               "Conf libc6 (2.39-0ubuntu8.6 Ubuntu:24.04/noble-updates [amd64])")))
        self.assertEqual(verdict, "lab-ubuntu: needs attention: reboot pending; 1 package update(s) pending")


class RebootTests(unittest.TestCase):
    """reboot.yml reboots exactly one acknowledged host, and only outside check mode."""

    def play(self):
        return tasks("playbooks/operations/reboot.yml")[0]

    def test_the_seeded_answer_is_the_one_the_playbook_accepts(self):
        expression = self.play()["vars"]["reboot_confirm"]
        prompt = load("seed-semaphore").REBOOT_PROMPT[0]
        for choice in prompt["values"]:
            self.assertIs(native(expression, **{prompt["name"]: choice["value"]}), True)
        self.assertIs(native(expression), False)
        for answer in ("", "reboot now", prompt["values"][0]["name"]):
            with self.subTest(answer=answer):
                self.assertIs(native(expression, **{prompt["name"]: answer}), False)

    def test_one_host_and_the_acknowledgement_are_checked_before_any_connection(self):
        pre = self.play()["pre_tasks"]
        names = [t["name"] for t in pre]
        preflight = names.index("Check scope and supported operating system")
        one = named(pre, "Reboot exactly one target per run")
        ack = named(pre, "Require an explicit acknowledgement")
        self.assertEqual(one["ansible.builtin.assert"]["that"], ["ansible_play_hosts_all | length == 1"])
        for task in (one, ack):
            self.assertLess(names.index(task["name"]), preflight)
            self.assertIn("always", task["tags"])
        that = ack["ansible.builtin.assert"]["that"]
        for confirm, check_mode, passes in ((True, False, True), (False, False, False), (False, True, True)):
            with self.subTest(confirm=confirm, check_mode=check_mode):
                self.assertIs(all(native("{{ " + c + " }}", reboot_confirm=confirm, ansible_check_mode=check_mode)
                                  for c in that), passes)
        # A key=value string is refused, as for the STIG approval.
        self.assertIs(native("{{ " + that[0] + " }}", reboot_confirm="true"), False)

    def test_the_controller_itself_is_refused_before_the_reboot(self):
        play = self.play()
        names = [task["name"] for task in play["tasks"]]
        guard = named(play["tasks"], "Refuse to reboot the controller this run comes from")
        # After the read it compares, and before the reboot.
        self.assertLess(names.index("Read the boot ID before the reboot"), names.index(guard["name"]))
        self.assertLess(names.index(guard["name"]), names.index("Reboot and wait for the target to answer again"))
        self.assertNotIn("when", guard)
        [that] = guard["ansible.builtin.assert"]["that"]
        self.assertEqual(that, "reboot_id_before != lookup('ansible.builtin.file', "
                               "'/proc/sys/kernel/random/boot_id') | trim")
        self.assertIn("Nothing was changed.", guard["ansible.builtin.assert"]["fail_msg"])

    @unittest.skipUnless(Templar and Path("/proc/sys/kernel/random/boot_id").exists(),
                         "needs ansible-core, as CI installs it, and Linux")
    def test_the_guard_compares_with_the_boot_id_of_the_machine_ansible_runs_on(self):
        play = self.play()
        [that] = named(play["tasks"], "Refuse to reboot the controller")["ansible.builtin.assert"]["that"]
        here = Path("/proc/sys/kernel/random/boot_id").read_text()
        # ansible-playbook loads the plugin lists at its start; a bare Templar does not.
        from ansible.plugins.loader import init_plugin_loader
        try:
            init_plugin_loader([])
        except RuntimeError:  # set up already by an earlier test
            pass
        for content, allowed in ((here, False), ("1111-aaaa\n", True)):
            with self.subTest(content=content):
                variables = self.registered(reboot_boot_id_before=encoded(content))
                self.assertIs(rendered(play, variables, "{{ " + that + " }}"), allowed)

    def test_check_mode_reads_and_reboots_nothing(self):
        play = self.play()
        reboots = [t for t in walk(play["tasks"]) if "ansible.builtin.reboot" in t]
        self.assertEqual(len(reboots), 1)
        self.assertEqual(reboots[0]["when"], "not ansible_check_mode")
        self.assertGreaterEqual(reboots[0]["ansible.builtin.reboot"]["reboot_timeout"], 600)
        after = named(play["tasks"], "Read the target after the reboot")
        self.assertEqual(after["when"], "not ansible_check_mode")
        preview = named(play["tasks"], "Say what a real run would do")
        self.assertEqual(preview["when"], "ansible_check_mode")
        for task in walk(play["tasks"]):
            if "ansible.builtin.command" in task:
                with self.subTest(task=task["name"]):
                    self.assertIs(task["changed_when"], False)
                    # The reads before the reboot also run in check mode, for its preview.
                    if task["name"] not in {t["name"] for t in after["block"]}:
                        self.assertIs(task["check_mode"], False)

    def registered(self, **changes):
        return dict({
            "inventory_hostname": "lab-alma", "reboot_target_ack": "REBOOT NOW", "ansible_check_mode": False,
            "reboot_boot_id_before": encoded("1111-aaaa\n"), "reboot_uptime_before": encoded("200000.5 1.0\n"),
            "reboot_failed_before": command(0, "unit.service loaded failed failed Unit"),
            "reboot_system_state": command(0, "running"),
            "reboot_boot_id_after": encoded("2222-bbbb\n"), "reboot_uptime_after": encoded("41.9 3.0\n"),
            "reboot_failed_after": command(0),
        }, **changes)

    def messages(self, **changes):
        play = self.play()
        variables = self.registered(**changes)
        report = named(play["tasks"], "Read the target after the reboot")["block"][-1]["ansible.builtin.debug"]["msg"]
        preview = named(play["tasks"], "Say what a real run would do")["ansible.builtin.debug"]["msg"]
        return ([" ".join(line.split()) for line in rendered(play, variables, report)],
                " ".join(rendered(play, variables, preview).split()))

    @unittest.skipUnless(Templar, "needs ansible-core, as CI installs it")
    def test_the_report_compares_the_boot_before_and_after(self):
        report, preview = self.messages()
        self.assertEqual(report, [
            "lab-alma rebooted and answers again.",
            "Boot ID: 1111-aaaa before, 2222-bbbb now (changed).",
            "Uptime: 2 d 7 h 33 min before, 41 s now.",
            "System state: running.",
            "Failed systemd units now: 0 (before the reboot: 1)."])
        self.assertEqual(preview, "CHECK MODE: a real run reboots lab-alma now and waits up to 15 minutes for it to "
                                  "answer again. Boot ID 1111-aaaa, up 2 d 7 h 33 min, 1 failed systemd unit(s). The "
                                  "acknowledgement was given. Nothing was changed.")
        report, preview = self.messages(reboot_system_state=command(124), reboot_target_ack="",
                                        reboot_failed_after=command(1, "Failed to connect to bus"))
        self.assertIn("System state: still starting after 5 minutes, or unknown.", report)
        self.assertIn("Failed systemd units now: unknown, systemctl could not list them (before the reboot: 1).",
                      report)
        report, _preview = self.messages(reboot_failed_after=command(0, "● nfs.mount loaded failed failed NFS"))
        self.assertIn("Failed systemd units now: 1: nfs.mount (before the reboot: 1).", report)
        self.assertIn("A real run also needs the acknowledgement, REBOOT NOW.", preview)


class PatchControllerTests(unittest.TestCase):
    """A patch run that reaches the controller it comes from never reboots it."""

    def block(self):
        [play] = yaml.safe_load((ROOT / "playbooks" / "patching" / "patch.yml").read_text())
        return play, named(play["tasks"], "Detect and optionally handle a reboot after real patching")["block"]

    def test_the_reboot_is_skipped_for_the_controller_itself(self):
        play, block = self.block()
        [reboot] = [task for task in block if "ansible.builtin.reboot" in task]
        self.assertEqual(reboot["when"], "lab_reboot_needed and allow_reboot and not lab_is_controller")
        read = named(play["tasks"], "Read the boot ID")
        self.assertEqual(read["ansible.builtin.slurp"]["src"], "/proc/sys/kernel/random/boot_id")
        # The controller is recognized before the first package changes, which already need to know it.
        names = [task["name"] for task in play["tasks"]]
        self.assertEqual(names[:4], [read["name"], "Recognize the controller this run comes from",
                                     "Upgrade Ubuntu packages without removals", "Install the EL reboot-check plugin"])
        # The reboot handling runs only after real patching.
        guarded = named(play["tasks"], "Detect and optionally handle a reboot after real patching")
        self.assertEqual(guarded["when"], "not ansible_check_mode")

    @unittest.skipUnless(Templar, "needs ansible-core, as CI installs it")
    def test_needrestart_is_suspended_only_on_the_controller_itself(self):
        # After a library update Ubuntu's needrestart restarts Semaphore, which would end the run halfway.
        for playbook, task_name, fact in (("patching/patch.yml", "Upgrade Ubuntu packages without removals", "lab_is_controller"),
                                          ("stig/apply.yml", "Apply the vendor remediation on Ubuntu", "stig_is_controller")):
            with self.subTest(playbook=playbook):
                [play] = yaml.safe_load((ROOT / "playbooks" / playbook).read_text())
                task = named(play["tasks"], task_name)
                self.assertEqual(task["when"], "ansible_facts['os_family'] == 'Debian'")
                self.assertEqual(rendered(play, {fact: True}, task["environment"]), {"NEEDRESTART_SUSPEND": "1"})
                self.assertEqual(rendered(play, {fact: False}, task["environment"]), {})
                names = [entry["name"] for entry in play["tasks"]]
                self.assertLess(names.index("Recognize the controller this run comes from"), names.index(task_name))

    @unittest.skipUnless(Templar and Path("/proc/sys/kernel/random/boot_id").exists(),
                         "needs ansible-core, as CI installs it, and Linux")
    def test_the_controller_is_told_apart_by_its_boot_id_and_reported(self):
        play, block = self.block()
        from ansible.plugins.loader import init_plugin_loader
        try:
            init_plugin_loader([])
        except RuntimeError:  # set up already by an earlier test
            pass
        here = Path("/proc/sys/kernel/random/boot_id").read_text()
        fact = named(play["tasks"], "Recognize the controller")["ansible.builtin.set_fact"]["lab_is_controller"]
        report = named(block, "Report the completed patch result")
        services = ("Services were not restarted on this controller, so that the run could finish: run sudo "
                    "needrestart from its own terminal when no task is running, or reboot it.")
        cases = ((here, True, True, "required and left alone: lab-alma is the controller this run comes from, and "
                                    "its reboot would stop the run. Restart it from its own terminal when no task "
                                    "is running, with sudo systemctl reboot"),
                 ("1111-aaaa\n", True, True, "completed and connection restored"),
                 (here, True, False, "required; left for the operator"),
                 (here, False, True, "not requested by the operating system"))
        for content, needed, allowed, expected in cases:
            with self.subTest(controller=content == here, needed=needed, allowed=allowed):
                variables = {"inventory_hostname": "lab-alma", "lab_boot_id": encoded(content),
                             "lab_reboot_needed": needed, "allow_reboot": allowed,
                             "ansible_facts": {"os_family": "RedHat"}}
                is_controller = rendered(play, variables, fact)
                self.assertIs(is_controller, content == here)
                variables.update(lab_is_controller=is_controller,
                                 lab_controller_note=trusted(report["vars"]["lab_controller_note"]),
                                 lab_services_note=trusted(report["vars"]["lab_services_note"]))
                reboots = rendered(play, variables, "{{ lab_reboot_needed and allow_reboot and not lab_is_controller }}")
                self.assertIs(reboots, needed and allowed and content != here)
                variables.update(lab_services_suffix=rendered(play, variables, report["vars"]["lab_services_suffix"]))
                message = " ".join(rendered(play, variables, report["ansible.builtin.debug"]["msg"]).split())
                self.assertEqual(message, f"lab-alma: updates completed. Reboot {expected}.")
                # Only an Ubuntu controller is told that its services still wait for a restart.
                variables["ansible_facts"] = {"os_family": "Debian"}
                variables.update(lab_services_suffix=rendered(play, variables, report["vars"]["lab_services_suffix"]))
                raw = rendered(play, variables, report["ansible.builtin.debug"]["msg"])
                self.assertEqual(" ".join(raw.split()), f"lab-alma: updates completed. Reboot {expected}."
                                                        + (f" {services}" if content == here else ""))
                # The sentence about the services follows on the same line of the log.
                self.assertNotIn(".\n", raw)


class StigApplyControllerTests(unittest.TestCase):
    """A STIG apply whose one target is the controller it comes from never reboots it."""

    def tasks(self):
        [play] = yaml.safe_load((ROOT / "playbooks" / "stig" / "apply.yml").read_text())
        return play, play["tasks"]

    def test_the_reboot_is_skipped_for_the_controller_itself(self):
        _play, tasks = self.tasks()
        names = [task["name"] for task in tasks]
        [reboot] = [task for task in tasks if "ansible.builtin.reboot" in task]
        self.assertEqual(reboot["when"], "allow_reboot and not stig_is_controller")
        read = named(tasks, "Read the boot ID")
        self.assertEqual(read["ansible.builtin.slurp"]["src"], "/proc/sys/kernel/random/boot_id")
        # Recognized before the fixes, which install packages, and so before the reboot as well.
        order = [read["name"], "Recognize the controller this run comes from", "Apply the vendor remediation on Ubuntu",
                 reboot["name"], "Record the posture after remediation", "Explain what to verify next"]
        self.assertEqual([name for name in names if name in order], order)

    @unittest.skipUnless(Templar and Path("/proc/sys/kernel/random/boot_id").exists(),
                         "needs ansible-core, as CI installs it, and Linux")
    def test_the_controller_is_told_apart_by_its_boot_id_and_told_to_restart_itself(self):
        play, tasks = self.tasks()
        from ansible.plugins.loader import init_plugin_loader
        try:
            init_plugin_loader([])
        except RuntimeError:  # set up already by an earlier test
            pass
        here = Path("/proc/sys/kernel/random/boot_id").read_text()
        fact = named(tasks, "Recognize the controller")["ansible.builtin.set_fact"]["stig_is_controller"]
        report = named(tasks, "Explain what to verify next")
        cases = ((here, True, "without the reboot you approved: lab-rhel is the controller this run comes from, and "
                              "its reboot would stop the run. Restart it from its own terminal when no task is "
                              "running, with sudo systemctl reboot, then run the audit; many STIG rules only take "
                              "effect after a reboot"),
                 ("1111-aaaa\n", True, "and rebooted"),
                 (here, False, "without a reboot; many STIG rules only take effect after one"),
                 ("1111-aaaa\n", False, "without a reboot; many STIG rules only take effect after one"))
        for content, allowed, expected in cases:
            with self.subTest(controller=content == here, allowed=allowed):
                variables = {"inventory_hostname": "lab-rhel", "stig_boot_id": encoded(content), "allow_reboot": allowed,
                             "ansible_facts": {"os_family": "RedHat"},
                             "stig_ssh_client_kept": trusted(report["vars"]["stig_ssh_client_kept"]),
                             "stig_ssh_client_left": trusted(report["vars"]["stig_ssh_client_left"])}
                is_controller = rendered(play, variables, fact)
                self.assertIs(is_controller, content == here)
                variables.update(stig_is_controller=is_controller)
                reboots = rendered(play, variables, "{{ allow_reboot and not stig_is_controller }}")
                self.assertIs(reboots, allowed and content != here)
                variables.update(stig_controller_note=trusted(report["vars"]["stig_controller_note"]))
                variables.update(stig_reboot_note=rendered(play, variables, report["vars"]["stig_reboot_note"]))
                variables.update(stig_ssh_client_note=rendered(play, variables, report["vars"]["stig_ssh_client_note"]))
                self.assertEqual(variables["stig_ssh_client_note"], "")
                message = " ".join(rendered(play, variables, report["ansible.builtin.debug"]["msg"]).split())
                self.assertTrue(message.startswith(f"lab-rhel: vendor remediation applied {expected}. Check console"),
                                message)
                self.assertNotIn("\n", rendered(play, variables, report["ansible.builtin.debug"]["msg"]).strip())
                # On Ubuntu the message says what became of the SSH client's files that usg leaves for root only.
                variables["ansible_facts"] = {"os_family": "Debian"}
                variables.update(stig_ssh_client_note=rendered(play, variables, report["vars"]["stig_ssh_client_note"]))
                message = " ".join(rendered(play, variables, report["ansible.builtin.debug"]["msg"]).split())
                kept = ("On this controller the files usg wrote in /etc/ssh/ssh_config.d were made readable again, mode "
                        "0644, so that ssh keeps working for the semaphore account and for you.")
                left = ("usg wrote files in /etc/ssh/ssh_config.d that only root can read. Until they are readable, with "
                        "sudo chmod 0644 /etc/ssh/ssh_config.d/*.conf, the ssh command ends with an error on this machine "
                        "for every account but root.")
                self.assertTrue(message.startswith(f"lab-rhel: vendor remediation applied {expected}. "
                                                   f"{kept if content == here else left} Check console"), message)
                self.assertNotIn("\n", rendered(play, variables, report["ansible.builtin.debug"]["msg"]).strip())


class PackageLockTests(unittest.TestCase):
    """A fresh VM can hold the package lock for minutes while it installs the image's own updates.

    Only the apt tasks use lock_timeout. ansible-core's dnf module accepts it and never
    reads it, and dnf itself waits until the lock is free; the dnf tasks carry the same
    value only so that every package task reads alike.
    """

    def test_apt_tasks_wait_for_the_lock_as_long_as_onboarding(self):
        onboarding = set()
        for path in ("onboard/new-vm/cloud-init.yaml", "onboard/existing/onboard-linux.sh"):
            text = (ROOT / path).read_text()
            onboarding |= {int(seconds) for seconds in re.findall(r"DPkg::Lock::Timeout=(\d+)", text)}
        (timeout,) = onboarding
        modules, files = set(), set()
        # The lessons, and the examples, such as the bootstrap playbook that onboards a VM.
        for path in sorted(path for folder in ("playbooks", "examples", "onboard", "platforms")
                           for path in (ROOT / folder).rglob("*.yml")):
            for task in package_tasks(yaml.safe_load(path.read_text())):
                module = next(key for key in task if key in ("ansible.builtin.apt", "ansible.builtin.dnf"))
                modules.add(module)
                files.add(str(path.relative_to(ROOT)))
                with self.subTest(path=str(path.relative_to(ROOT)), task=task["name"]):
                    self.assertEqual(task[module].get("lock_timeout"), timeout)
        self.assertEqual(modules, {"ansible.builtin.apt", "ansible.builtin.dnf"})
        self.assertIn("onboard/existing/bootstrap-existing-vm.yml", files)


class PreflightPathTests(unittest.TestCase):
    """The preflight loads a vars file on the controller. A target reports its own facts, so they
    may choose between the reviewed files and never name one."""

    SYSTEMS = (("Ubuntu", "24.04", "24", "Debian"), ("AlmaLinux", "9.8", "9", "RedHat"),
               ("Rocky", "9.6", "9", "RedHat"), ("RedHat", "9.8", "9", "RedHat"))
    # What a taken-over target could report to load another host's variables, such as its sudo password.
    CRAFTED = "../../inventories/host_vars/lab-alma"

    def facts(self, distribution, version, major, family):
        return {"distribution": distribution, "distribution_version": version,
                "distribution_major_version": major, "os_family": family}

    def accepted(self, facts):
        task = named(tasks("playbooks/tasks/preflight.yml"), "Reject operating systems outside this lesson")
        return native("{{ " + task["ansible.builtin.assert"]["that"][0] + " }}", ansible_facts=facts)

    def loaded(self, facts):
        task = named(tasks("playbooks/tasks/preflight.yml"), "Load the reviewed names for this OS family")
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        environment.filters["dirname"] = os.path.dirname
        template = environment.from_string(task["ansible.builtin.include_vars"]["file"])
        # The first folder Ansible searches is the task file's own, whatever folder the playbook is in.
        return template.render(ansible_search_path=["/lab/playbooks/tasks", "/lab/playbooks/baseline"], ansible_facts=facts)

    def test_each_supported_system_loads_its_own_family_file(self):
        for system in self.SYSTEMS:
            with self.subTest(system=system[0]):
                self.assertIs(self.accepted(self.facts(*system)), True)
                self.assertEqual(self.loaded(self.facts(*system)), f"/lab/playbooks/vars/{system[3]}.yml")
                self.assertTrue((ROOT / "playbooks" / "vars" / f"{system[3]}.yml").is_file())

    def test_a_family_that_does_not_match_the_distribution_is_refused(self):
        for distribution, version, major, family in self.SYSTEMS:
            for other in sorted({"Debian", "RedHat", "debian", self.CRAFTED} - {family}):
                with self.subTest(distribution=distribution, family=other):
                    self.assertIs(self.accepted(self.facts(distribution, version, major, other)), False)

    def test_no_string_the_target_reports_becomes_part_of_the_path(self):
        task = named(tasks("playbooks/tasks/preflight.yml"), "Load the reviewed names for this OS family")
        self.assertNotIn("os_family", task["ansible.builtin.include_vars"]["file"])
        for distribution in ("Ubuntu", "AlmaLinux", self.CRAFTED, ""):
            with self.subTest(distribution=distribution):
                path = self.loaded(self.facts(distribution, self.CRAFTED, self.CRAFTED, self.CRAFTED))
                self.assertIn(path, {"/lab/playbooks/vars/Debian.yml", "/lab/playbooks/vars/RedHat.yml"})


# Runs in place of a target's interpreter: it runs each module with the test's Python, then
# reports the facts in the file it is given instead of the module's own.
REPORT_FACTS = """import json
import sys

text = sys.stdin.read()
try:
    result = json.loads(text)
except ValueError:
    result = None
if isinstance(result, dict) and "ansible_os_family" in result.get("ansible_facts", {}):
    with open(sys.argv[1]) as stream:
        result["ansible_facts"].update(json.load(stream))
    text = json.dumps(result)
sys.stdout.write(text)
"""


@unittest.skipUnless(shutil.which("ansible-playbook") and os.access("/usr/bin/python3", os.X_OK),
                     "needs ansible-playbook, as CI installs it, and /usr/bin/python3")
class ReportedFactsTests(unittest.TestCase):
    """ping.yml and its preflight, run by ansible-playbook against a stand-in target.

    The target reports the facts each test gives it, as one whose root or svc_ansible account
    was taken over could, and its package-binding check finds stand-in apt and dnf modules.
    Nothing contacts a host.
    """

    UBUNTU = {"ansible_distribution": "Ubuntu", "ansible_distribution_version": "24.04",
              "ansible_distribution_major_version": "24", "ansible_os_family": "Debian",
              "ansible_service_mgr": "systemd"}

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        (self.work / "stubs").mkdir()
        for module in ("apt", "dnf"):
            (self.work / "stubs" / f"{module}.py").write_text("")
        (self.work / "report.py").write_text(REPORT_FACTS)
        python, report, facts = (shlex.quote(str(path)) for path in
                                 (sys.executable, self.work / "report.py", self.work / "facts.json"))
        interpreter = self.work / "python"
        interpreter.write_text(f"#!/bin/bash\nset -o pipefail\nPYTHONPATH={shlex.quote(str(self.work / 'stubs'))}"
                               f' {python} "$@" | {python} -I {report} {facts}\n')
        interpreter.chmod(0o755)
        (self.work / "inventory.ini").write_text(
            f"[ubuntu]\nlab-ubuntu ansible_host=ubuntu.example.test ansible_connection=local"
            f" ansible_python_interpreter={interpreter}\n\n[lab:children]\nubuntu\n")
        # Another host's variables, which only the inventory may give to lab-alma.
        (self.work / "host_vars").mkdir()
        (self.work / "host_vars" / "lab-alma.yml").write_text("ansible_host: alma.example.test\n")
        (self.work / "collections").mkdir()

    def ping(self, playbook=None, **facts):
        (self.work / "facts.json").write_text(json.dumps(dict(self.UBUNTU, **facts)))
        environment = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / "ansible.cfg"),
                           ANSIBLE_COLLECTIONS_PATH=str(self.work / "collections"),
                           ANSIBLE_COLLECTIONS_SCAN_SYS_PATH="False")
        return subprocess.run(["ansible-playbook", "-i", str(self.work / "inventory.ini"),
                               str(playbook or ROOT / "playbooks" / "baseline" / "ping.yml"), "--limit", "lab-ubuntu"],
                              capture_output=True, text=True, timeout=180, cwd=self.work, env=environment)

    def test_a_target_that_reports_its_system_passes(self):
        result = self.ping()
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])
        self.assertIn("lab-ubuntu (ubuntu.example.test) runs Ubuntu 24.04.", result.stdout)

    def test_the_shared_checks_find_their_files_from_a_playbook_in_any_folder(self):
        # The thin file at the earlier path, and playbooks of a reader's own: directly in playbooks/, as
        # releases before v1.12.0 had theirs, in playbooks/site/, and one folder deeper.
        tree = self.work / "lab" / "playbooks"
        shutil.copytree(ROOT / "playbooks", tree)
        own = (ROOT / "playbooks" / "baseline" / "ping.yml").read_text()
        (tree / "my-flat.yml").write_text(own.replace("../tasks/preflight.yml", "tasks/preflight.yml"))
        (tree / "site" / "mine.yml").write_text(own)
        (tree / "site" / "deeper").mkdir()
        (tree / "site" / "deeper" / "mine.yml").write_text(own.replace("../tasks/preflight.yml", "../../tasks/preflight.yml"))
        for playbook in ("ping.yml", "baseline/ping.yml", "my-flat.yml", "site/mine.yml", "site/deeper/mine.yml"):
            with self.subTest(playbook=playbook):
                result = self.ping(playbook=tree / playbook)
                self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])
                self.assertIn("TASK [Load the reviewed names for this OS family]", result.stdout)
                self.assertIn("lab-ubuntu (ubuntu.example.test) runs Ubuntu 24.04.", result.stdout)

    def test_a_crafted_os_family_stops_before_any_file_is_loaded(self):
        crafted = os.path.relpath(self.work / "host_vars" / "lab-alma", ROOT / "playbooks" / "vars")
        result = self.ping(ansible_os_family=crafted)
        self.assertNotEqual(result.returncode, 0, result.stdout[-3000:])
        self.assertIn("TASK [Reject operating systems outside this lesson]", result.stdout)
        self.assertIn(f"Found Ubuntu 24.04 of the {crafted} family using systemd.", result.stdout)
        self.assertNotIn("TASK [Load the reviewed names for this OS family]", result.stdout)
        self.assertNotIn("alma.example.test", result.stdout)


class ControllerPathTests(unittest.TestCase):
    """No file on the controller is named by what a target reports: its facts, or the output of
    a task that ran on it.

    The values the controller acts on are those of tasks delegated to it, include_vars, the
    sources of copy and template, fetch destinations, vars_files and lookups, each with the
    play variables, set_fact values and task variables it names. The playbooks read facts
    only through ansible_facts. The preflight's include_vars, where a fact chooses between two
    reviewed files, is the one exception; PreflightPathTests renders it.
    """

    TARGET = re.compile(r"\bansible_facts\b|\bhostvars\b")

    def values(self, play):
        """Yield each value the controller acts on, and each definition of a variable it names, by task."""
        lookups = re.compile(r"(?:lookup|query)\([^)]*\)")
        definitions = {name: [json.dumps(value)] for name, value in play.get("vars", {}).items()}
        found = [("vars_files", json.dumps(play.get("vars_files", [])))]
        found += [("play vars", call) for call in lookups.findall(json.dumps(play.get("vars")))]
        for task in walk(play.get("pre_tasks", []) + play.get("tasks", []) + play.get("handlers", [])):
            module = next((key for key in task if key.startswith("ansible.builtin.")), None)
            arguments = task.get(module) if isinstance(task.get(module), dict) else {}
            assigned = dict(task.get("vars", {}))
            if module == "ansible.builtin.set_fact":
                assigned.update(arguments)
            for name, value in assigned.items():
                definitions.setdefault(name, []).append(json.dumps(value))
            on_controller = task.get("delegate_to") == "localhost"
            if "register" in task:
                # The output of a task that ran on a target is the target's word.
                definitions.setdefault(task["register"], []).append(
                    json.dumps([task.get(module), task.get("args")]) if on_controller else "ansible_facts")
            if on_controller:
                found.append((task["name"], json.dumps([task.get(module), task.get("args"), task.get("loop")])))
            elif module == "ansible.builtin.include_vars":
                found.append((task["name"], json.dumps(task[module])))
            elif module in ("ansible.builtin.copy", "ansible.builtin.template") and not arguments.get("remote_src"):
                found.append((task["name"], json.dumps(arguments.get("src"))))
            elif module == "ansible.builtin.fetch":
                found.append((task["name"], json.dumps(arguments["dest"])))
            found += [(task["name"], call) for call in lookups.findall(json.dumps(task))]
        for name, text in found:
            seen, pending = set(), [text]
            while pending:
                current = pending.pop()
                yield name, current
                for word in set(re.findall(r"\b[a-z_]\w*", current)) - seen:
                    seen.add(word)
                    pending += definitions.get(word, [])

    def test_only_the_preflight_lets_a_fact_choose_a_file(self):
        named_by_target, checked = set(), set()
        # The per-system STIG playbooks only import the shared ones.
        for pattern in ("playbooks/*/*.yml", "onboard/existing/*.yml", "examples/semaphore/*.yml"):
            for path in sorted(path for path in ROOT.glob(pattern) if path.parent.name not in ("tasks", "vars")):
                for play in yaml.safe_load(path.read_text()):
                    # A play on the controller itself has no target.
                    if play["hosts"] == "localhost":
                        continue
                    for name, text in self.values(play):
                        checked.add(name)
                        if self.TARGET.search(text):
                            named_by_target.add(name)
        self.assertEqual(named_by_target, {"Load the reviewed names for this OS family"})
        # Among them the STIG evidence the controller fetches and reads, and the keys it measures.
        for name in ("Fetch the results and report to the controller for phase {{ stig_phase }}",
                     "Summarize the fetched XCCDF result on the controller",
                     "Look for the local content file on the controller", "Measure each listed key on the controller",
                     "vars_files", "play vars"):
            self.assertIn(name, checked)


class LabFolderTests(unittest.TestCase):
    def test_seeded_lab_folder_contains_every_script_the_playbooks_call(self):
        # Join continued lines so a wrapped install command still counts as one.
        installer = (ROOT / "controller" / "controller-common.sh").read_text().replace("\\\n", " ")
        for name in ("install-controller.sh", "install-controller-el9.sh"):
            with self.subTest(installer=name):
                source = (ROOT / "controller" / name).read_text()
                self.assertIn('source "$script_dir/controller-common.sh"', source)
                self.assertRegex(source, r"(?m)^controller_seed_lab$")
        called = set()
        for playbook in (ROOT / "playbooks").rglob("*.yml"):
            called |= set(re.findall(r"/scripts/([\w.-]+\.py)", playbook.read_text()))
        self.assertIn("summarize_xccdf.py", called)
        for script in called:
            with self.subTest(script=script):
                self.assertTrue((ROOT / "scripts" / script).is_file())
                copies = [line for line in installer.splitlines()
                          if f'"$repo_dir/scripts/{script}"' in line and '"$lab_dir/scripts/' in line]
                self.assertTrue(copies, f"controller-common.sh does not copy {script} into the lab folder")


if __name__ == "__main__":
    unittest.main()
