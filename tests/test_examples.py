"""Offline checks for secret generation and assessment interpretation."""

import base64
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
import xml.etree.ElementTree as ET


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


if __name__ == "__main__":
    unittest.main()
