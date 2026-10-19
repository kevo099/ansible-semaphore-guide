"""Offline checks that the lesson playbooks agree with each other and with the seeder."""

import ast
import datetime
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
        modules = set()
        for path in sorted((ROOT / "playbooks").rglob("*.yml")):
            for task in package_tasks(yaml.safe_load(path.read_text())):
                module = next(key for key in task if key in ("ansible.builtin.apt", "ansible.builtin.dnf"))
                modules.add(module)
                with self.subTest(path=str(path.relative_to(ROOT)), task=task["name"]):
                    self.assertEqual(task[module].get("lock_timeout"), timeout)
        self.assertEqual(modules, {"ansible.builtin.apt", "ansible.builtin.dnf"})


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
