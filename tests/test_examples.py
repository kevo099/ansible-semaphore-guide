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
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
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
                lines = (ROOT / "templates" / unit).read_text().splitlines()
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
        content = yaml.safe_load((ROOT / "examples" / "azure" / playbook).read_text())
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
        play = yaml.safe_load((ROOT / "examples" / "azure" / "controller.yml").read_text())[0]
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
                tasks = yaml.safe_load((ROOT / "examples" / "azure" / playbook).read_text())[0]["tasks"]
                task = next(t for t in tasks if t["name"].startswith(task_prefix))
                self.assertEqual(task["azure.azcollection.azure_rm_virtualmachine"]["plan"],
                                 "{{ " + owner + ".plan | default(omit) }}")


@unittest.skipUnless(shutil.which("ansible-playbook"), "needs ansible-playbook, as CI installs it")
class BootstrapKeyPathTests(unittest.TestCase):
    """bootstrap-existing-vm.yml must read sshd's AuthorizedKeysFile the way Ansible renders it.

    Plain Jinja and ansible-core treat backslash escapes in this expression differently, so
    the expression runs through ansible-playbook itself.
    """

    CASES = [
        (["authorizedkeysfile .ssh/authorized_keys"], ["/home/svc_ansible/.ssh/authorized_keys"]),
        (["authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2"],
         ["/home/svc_ansible/.ssh/authorized_keys", "/home/svc_ansible/.ssh/authorized_keys2"]),
        (["authorizedkeysfile %h/.ssh/authorized_keys"], ["/home/svc_ansible/.ssh/authorized_keys"]),
        (["authorizedkeysfile /etc/ssh/keys/%u"], ["/etc/ssh/keys/svc_ansible"]),
        # No AuthorizedKeysFile line reads as "none", which is not the account's file, so the
        # playbook's check refuses the policy.
        (["port 22"], ["/home/svc_ansible/none"]),
    ]

    def test_relative_token_and_absolute_paths_resolve(self):
        play = yaml.safe_load((ROOT / "examples" / "bootstrap-existing-vm.yml").read_text())[0]
        expression = None
        for task in play["tasks"]:
            for inner in task.get("block", []):
                if "bootstrap_key_paths" in inner.get("vars", {}):
                    expression = inner["vars"]["bootstrap_key_paths"]
        self.assertIsNotNone(expression, "bootstrap_key_paths not found")
        tasks = [{"name": f"case {index}", "ansible.builtin.debug": {"msg": "{{ bootstrap_key_paths }}"},
                  "vars": {"bootstrap_sshd_policy": {"stdout_lines": lines}, "bootstrap_key_paths": expression}}
                 for index, (lines, _expected) in enumerate(self.CASES)]
        with tempfile.TemporaryDirectory() as work:
            playbook = Path(work) / "paths.yml"
            playbook.write_text(yaml.safe_dump([{"hosts": "localhost", "gather_facts": False, "tasks": tasks}]))
            config = Path(work) / "ansible.cfg"
            config.write_text("[defaults]\n")
            environment = dict(os.environ, ANSIBLE_STDOUT_CALLBACK="json", ANSIBLE_LOCALHOST_WARNING="False",
                               ANSIBLE_INVENTORY_UNPARSED_WARNING="False", ANSIBLE_CONFIG=str(config))
            result = subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
                                    capture_output=True, text=True, timeout=120, cwd=work, env=environment)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
        report = json.loads(result.stdout[result.stdout.index("{"):])
        rendered = [task["hosts"]["localhost"]["msg"] for task in report["plays"][0]["tasks"]]
        self.assertEqual(rendered, [expected for _lines, expected in self.CASES])


if __name__ == "__main__":
    unittest.main()
