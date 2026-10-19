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
    """Azure refuses an OS disk smaller than its image; Red Hat's RHEL 9 images are 64 GB."""

    def disk_expression(self, playbook, task_prefix):
        tasks = yaml.safe_load((ROOT / "examples" / "azure" / playbook).read_text())[0]["tasks"]
        task = next(t for t in tasks if t["name"].startswith(task_prefix))
        return task["azure.azcollection.azure_rm_virtualmachine"]["os_disk_size_gb"]

    def render(self, expression, **variables):
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        return int(environment.from_string(expression).render(**variables).strip())

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
