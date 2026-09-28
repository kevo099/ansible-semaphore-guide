"""Offline checks for the Semaphore seeding plan; nothing here talks to a server."""

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = load("seed-semaphore")
IDS = {"none_key": 1, "ssh_key": 2, "repository": 3, "inventory": 4,
       "environments": {"Practice defaults": 5, "Allow required reboot": 6, "Local SCAP content": 8}}


class SeedPlanTests(unittest.TestCase):
    def plan(self):
        return seed.seed_plan(7, IDS, "/opt/ansible-lab", "svc_ansible")

    def test_lab_dir_must_be_absolute(self):
        self.assertEqual(seed.lab_dir_path("/opt/ansible-lab/"), "/opt/ansible-lab")
        for bad in ("opt/ansible-lab", "./lab", "/"):
            with self.assertRaises(ValueError):
                seed.lab_dir_path(bad)

    def test_repository_is_local_path_and_inventory_is_a_file_in_it(self):
        plan = self.plan()
        self.assertTrue(plan["repository"]["git_url"].startswith("/"))
        self.assertEqual(plan["repository"]["ssh_key_id"], IDS["none_key"])
        self.assertEqual(plan["inventory"]["type"], "file")
        self.assertEqual(plan["inventory"]["repository_id"], IDS["repository"])
        self.assertEqual(plan["inventory"]["ssh_key_id"], IDS["ssh_key"])
        self.assertEqual(plan["inventory"]["inventory"], "inventories/lab.ini")

    def test_every_template_is_scoped_and_points_at_a_guide_playbook(self):
        plan = self.plan()
        playbooks = {p.name for p in (ROOT / "playbooks").glob("*.yml")}
        self.assertEqual(len(plan["templates"]), len(seed.LESSONS))
        for template in plan["templates"]:
            arguments = json.loads(template["arguments"])
            # The limit lives in the template's Ansible options, never duplicated as an argument.
            self.assertNotIn("--limit", " ".join(arguments))
            if (template["playbook"].endswith("stig-apply.yml")
                    or template["environment_ids"] == [IDS["environments"]["Local SCAP content"]]):
                self.assertEqual(template["task_params"], {"limit": [], "allow_override_limit": True})
            else:
                self.assertEqual(template["task_params"], {"limit": ["lab"]})
            self.assertEqual(template["app"], "ansible")
            self.assertIn(Path(template["playbook"]).name, playbooks)
            self.assertNotIn("environment_id", template)
            self.assertEqual(len(template["environment_ids"]), 1)
            self.assertIn(template["environment_ids"][0], IDS["environments"].values())

    def test_templates_do_not_share_mutable_options(self):
        plan = self.plan()
        plan["templates"][0]["task_params"]["limit"].append("changed")
        self.assertEqual(self.plan()["templates"][0]["task_params"], {"limit": ["lab"]})

    def test_preview_templates_never_change_targets(self):
        for template in self.plan()["templates"]:
            if "preview" in template["name"].lower():
                self.assertIn("--check", json.loads(template["arguments"]))

    def test_only_the_named_reboot_template_allows_reboot(self):
        plan = self.plan()
        reboot_env = IDS["environments"]["Allow required reboot"]
        allowed = [t["name"] for t in plan["templates"] if reboot_env in t["environment_ids"]]
        self.assertEqual(allowed, ["Patch, allow required reboot", "STIG apply, allow required reboot"])
        for template in plan["templates"]:
            if reboot_env in template["environment_ids"]:
                self.assertIn("allow required reboot", template["name"].lower())
        self.assertEqual(json.loads(plan["environments"]["Allow required reboot"]["json"]), {"allow_reboot": True})
        self.assertEqual(json.loads(plan["environments"]["Practice defaults"]["json"]), {})

    def test_api_bodies_may_be_json_or_plain_text(self):
        self.assertEqual(seed.parse_body(b"pong"), "pong")
        self.assertEqual(seed.parse_body(b'{"id": 3}'), {"id": 3})
        self.assertIsNone(seed.parse_body(b""))

    def test_stig_apply_templates_prompt_for_a_recovery_point(self):
        for template in self.plan()["templates"]:
            if template["playbook"].endswith("stig-apply.yml"):
                self.assertEqual(template["survey_vars"][0]["name"], "recovery_snapshot_ack")
                self.assertTrue(template["survey_vars"][0]["required"])
                self.assertEqual(template["survey_vars"][0]["values"][0]["value"], "SNAPSHOT READY")
            else:
                self.assertEqual(template["survey_vars"], [])

    def test_plan_carries_no_private_key_material(self):
        self.assertNotIn("PRIVATE", json.dumps(self.plan()))


    def test_local_content_template_audits_with_placeholders_the_playbook_refuses(self):
        plan = self.plan()
        local = [t for t in plan["templates"]
                 if t["environment_ids"] == [IDS["environments"]["Local SCAP content"]]]
        self.assertEqual([t["name"] for t in local], ["STIG audit, local SCAP content"])
        self.assertEqual(local[0]["playbook"], "playbooks/stig-audit.yml")
        self.assertEqual(local[0]["survey_vars"], [])
        values = json.loads(plan["environments"]["Local SCAP content"]["json"])
        self.assertEqual(set(values), {"stig_content_file", "stig_content_profile"})
        self.assertTrue(all("REPLACE_WITH" in value for value in values.values()))


if __name__ == "__main__":
    unittest.main()
