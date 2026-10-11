"""Offline checks that the lesson playbooks agree with each other and with the seeder."""

import ast
import importlib.util
import json
from pathlib import Path
import re
import unittest

import jinja2
from jinja2.nativetypes import NativeEnvironment
import yaml


ROOT = Path(__file__).resolve().parents[1]
# Each accepted Enterprise Linux distribution and the data stream its own
# scap-security-guide package ships. Update both playbooks and this table together.
VENDOR_DATA_STREAMS = {"RedHat": "rhel9", "AlmaLinux": "almalinux9", "Rocky": "rl9"}
STIG_PLAYBOOKS = ("playbooks/stig-audit.yml", "playbooks/stig-apply.yml")


def tasks(relative):
    return yaml.safe_load((ROOT / relative).read_text())


def named(task_list, prefix):
    return next(t for t in task_list if t.get("name", "").startswith(prefix))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
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
        return tasks("playbooks/stig-apply.yml")[0]["vars"]["stig_confirm"]

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
        return native(task["ansible.builtin.debug"]["msg"], stig_summary=summary)

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
                self.assertFalse(self.warns(summary))


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
        self.assertEqual(found, sorted(f"{folder}/{kind}.yml" for _l, folder, _g, _f in systems
                                       for kind in ("apply", "audit")))
        scopes = set()
        for _label, folder, _group, _file in systems:
            for kind, shared in (("audit", "stig-audit.yml"), ("apply", "stig-apply.yml")):
                with self.subTest(playbook=f"{folder}/{kind}.yml"):
                    (entry,) = tasks(f"playbooks/stig/{folder}/{kind}.yml")
                    self.assertEqual(entry["ansible.builtin.import_playbook"], f"../../../{shared}")
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
            self.assertEqual(tasks(playbook)[0]["vars_files"], ["vars/stig_systems.yml"])

    def test_an_audit_with_no_host_of_its_system_stops_with_an_explanation(self):
        audit = tasks("playbooks/stig-audit.yml")[0]["pre_tasks"]
        stop = named(audit, "Stop when no host in the run has the system this playbook audits")
        self.assertIn("select('equalto', stig_os_scope)", " ".join(stop["when"]))
        names = [t["name"] for t in audit]
        self.assertLess(names.index(stop["name"]), next(i for i, t in enumerate(audit)
                                                        if t.get("ansible.builtin.meta") == "end_host"))

    def test_audit_skips_and_apply_refuses_another_system(self):
        audit = tasks("playbooks/stig-audit.yml")[0]["pre_tasks"]
        end = next(t for t in audit if t.get("ansible.builtin.meta") == "end_host")
        self.assertEqual(end["when"], "stig_os_scope | length > 0 and stig_os_key != stig_os_scope")
        apply = tasks("playbooks/stig-apply.yml")[0]["pre_tasks"]
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


class LabFolderTests(unittest.TestCase):
    def test_seeded_lab_folder_contains_every_script_the_playbooks_call(self):
        # Join continued lines so a wrapped install command still counts as one.
        installer = (ROOT / "scripts" / "controller-common.sh").read_text().replace("\\\n", " ")
        for name in ("install-controller.sh", "install-controller-el9.sh"):
            with self.subTest(installer=name):
                source = (ROOT / "scripts" / name).read_text()
                self.assertIn('source "$script_dir/controller-common.sh"', source)
                self.assertRegex(source, r"(?m)^controller_seed_lab$")
        called = set()
        for playbook in (ROOT / "playbooks").rglob("*.yml"):
            called |= set(re.findall(r"\.\./scripts/([\w.-]+)", playbook.read_text()))
        self.assertIn("summarize_xccdf.py", called)
        for script in called:
            with self.subTest(script=script):
                self.assertTrue((ROOT / "scripts" / script).is_file())
                copies = [line for line in installer.splitlines()
                          if f'"$repo_dir/scripts/{script}"' in line and '"$lab_dir/scripts/' in line]
                self.assertTrue(copies, f"controller-common.sh does not copy {script} into the lab folder")


if __name__ == "__main__":
    unittest.main()
