"""Offline checks that the lesson playbooks agree with each other and with the seeder."""

import ast
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
STIG_PLAYBOOKS = ("playbooks/stig-audit.yml", "playbooks/stig-apply.yml")


def tasks(relative):
    return yaml.safe_load((ROOT / relative).read_text())


def named(task_list, prefix):
    return next(t for t in task_list if t.get("name", "").startswith(prefix))


def walk(task_list, inherited=None):
    """Yield each task with the become and delegate_to it inherits, through blocks and imports."""
    for task in task_list or []:
        effective = dict(inherited or {}, **{key: task[key] for key in ("become", "delegate_to") if key in task})
        if "ansible.builtin.import_tasks" in task:
            yield from walk(tasks(f"playbooks/{task['ansible.builtin.import_tasks']}"), effective)
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
        for playbook in sorted((ROOT / "playbooks").glob("*.yml")):
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
    SUDO_PLAYBOOKS = ("playbooks/baseline.yml", "playbooks/users.yml", "playbooks/webserver.yml",
                      "playbooks/patch.yml") + STIG_PLAYBOOKS
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
        for playbook, decision in (("playbooks/stig-audit.yml", "Leave hosts of other systems to their own playbook"),
                                   ("playbooks/stig-apply.yml", "Refuse a host that another system's playbook covers")):
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


class PackageLockTests(unittest.TestCase):
    """A fresh VM can hold the package lock for minutes while it installs the image's own updates.

    Only the apt tasks use lock_timeout. ansible-core's dnf module accepts it and never
    reads it, and dnf itself waits until the lock is free; the dnf tasks carry the same
    value only so that every package task reads alike.
    """

    def test_apt_tasks_wait_for_the_lock_as_long_as_onboarding(self):
        onboarding = set()
        for path in ("examples/onboard/cloud-init.yaml", "examples/onboard/onboard-linux.sh"):
            text = (ROOT / path).read_text()
            onboarding |= {int(seconds) for seconds in re.findall(r"DPkg::Lock::Timeout=(\d+)", text)}
        (timeout,) = onboarding
        modules, files = set(), set()
        # The lessons, and the examples, such as the bootstrap playbook that onboards a VM.
        for path in sorted((ROOT / "playbooks").rglob("*.yml")) + sorted((ROOT / "examples").rglob("*.yml")):
            for task in package_tasks(yaml.safe_load(path.read_text())):
                module = next(key for key in task if key in ("ansible.builtin.apt", "ansible.builtin.dnf"))
                modules.add(module)
                files.add(str(path.relative_to(ROOT)))
                with self.subTest(path=str(path.relative_to(ROOT)), task=task["name"]):
                    self.assertEqual(task[module].get("lock_timeout"), timeout)
        self.assertEqual(modules, {"ansible.builtin.apt", "ansible.builtin.dnf"})
        self.assertIn("examples/bootstrap-existing-vm.yml", files)


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
        template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            task["ansible.builtin.include_vars"]["file"])
        return template.render(playbook_dir="/lab/playbooks", ansible_facts=facts)

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

    def ping(self, **facts):
        (self.work / "facts.json").write_text(json.dumps(dict(self.UBUNTU, **facts)))
        environment = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / "ansible.cfg"),
                           ANSIBLE_COLLECTIONS_PATH=str(self.work / "collections"),
                           ANSIBLE_COLLECTIONS_SCAN_SYS_PATH="False")
        return subprocess.run(["ansible-playbook", "-i", str(self.work / "inventory.ini"),
                               str(ROOT / "playbooks" / "ping.yml"), "--limit", "lab-ubuntu"],
                              capture_output=True, text=True, timeout=180, cwd=self.work, env=environment)

    def test_a_target_that_reports_its_system_passes(self):
        result = self.ping()
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])
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
        for pattern in ("playbooks/*.yml", "examples/*.yml", "examples/semaphore/*.yml"):
            for path in sorted(ROOT.glob(pattern)):
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
