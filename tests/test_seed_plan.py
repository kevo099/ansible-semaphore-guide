"""Offline checks for the Semaphore seeding plan; nothing here talks to a server."""

import importlib.util
import json
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "controller" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = load("seed-semaphore")
IDS = {"none_key": 1, "ssh_key": 2, "repository": 3, "inventory": 4,
       "environments": {"Defaults": 5, "Allow required reboot": 6, "DISA SCAP file · RHEL 9": 8,
                        "DISA SCAP file · Ubuntu 24.04": 9}}
GROUP_OF_PLAYBOOK = {f"playbooks/stig/{folder}/audit.yml": group for _label, folder, group, _file in seed.STIG_SYSTEMS}


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
        self.assertEqual(len(plan["templates"]), len(seed.LESSONS))
        self.assertEqual(len(plan["templates"]), 24)
        for template in plan["templates"]:
            arguments = json.loads(template["arguments"])
            # The limit lives in the template's Ansible options, never duplicated as an argument.
            self.assertNotIn("--limit", " ".join(arguments))
            if template["playbook"].endswith("/apply.yml") or template["playbook"] == "playbooks/operations/reboot.yml":
                self.assertEqual(template["task_params"], {"limit": [], "allow_override_limit": True})
            elif template["playbook"] in GROUP_OF_PLAYBOOK:
                self.assertEqual(template["task_params"], {"limit": [GROUP_OF_PLAYBOOK[template["playbook"]]]})
            else:
                self.assertEqual(template["task_params"], {"limit": ["lab"]})
            self.assertEqual(template["app"], "ansible")
            self.assertTrue((ROOT / template["playbook"]).is_file(), template["playbook"])
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
        self.assertEqual(allowed, ["Patch, allow required reboot"] + [
            f"{label} · STIG apply, allow required reboot" for label, *_rest in seed.STIG_SYSTEMS])
        for template in plan["templates"]:
            if reboot_env in template["environment_ids"]:
                self.assertIn("allow required reboot", template["name"].lower())
        self.assertEqual(json.loads(plan["environments"]["Allow required reboot"]["json"]), {"allow_reboot": True})
        self.assertEqual(json.loads(plan["environments"]["Defaults"]["json"]), {})

    def test_api_bodies_may_be_json_or_plain_text(self):
        self.assertEqual(seed.parse_body(b"pong"), "pong")
        self.assertEqual(seed.parse_body(b'{"id": 3}'), {"id": 3})
        self.assertIsNone(seed.parse_body(b""))

    def test_stig_apply_templates_prompt_for_a_recovery_point(self):
        for template in self.plan()["templates"]:
            if template["playbook"].endswith("/apply.yml"):
                self.assertEqual(template["survey_vars"][0]["name"], "recovery_snapshot_ack")
                self.assertTrue(template["survey_vars"][0]["required"])
                self.assertEqual(template["survey_vars"][0]["values"][0]["value"], "SNAPSHOT READY")
            elif template["playbook"] == "playbooks/operations/reboot.yml":
                self.assertEqual(template["survey_vars"], seed.REBOOT_PROMPT)
            else:
                self.assertEqual(template["survey_vars"], [])

    def test_the_tabs_are_the_features_in_the_order_releases_added_them(self):
        plan = self.plan()
        # An update adds a missing tab after the existing ones, so a fresh seed puts the newest last too.
        self.assertEqual(seed.VIEWS[-2:], [("Operations", ["Health report", "Reboot one target"]),
                                           ("Examples", ["Users", "Webserver"])])
        self.assertEqual([title for title, _names in seed.VIEWS],
                         ["Baseline", "Patching"] + [f"STIG · {label}" for label, *_rest in seed.STIG_SYSTEMS]
                         + ["Operations", "Examples"])
        self.assertEqual(seed.VIEWS[0], ("Baseline", ["Ping", "Baseline preview", "Baseline apply"]))
        positions = {title: body["position"] for title, body in plan["views"].items()}
        self.assertEqual(max(positions, key=positions.get), "Examples")
        # Semaphore's own All tab has position 0; a seeded tab there would share its place.
        self.assertEqual(sorted(positions.values()), list(range(1, len(seed.VIEWS) + 1)))
        # No name of today has the wording of the earlier releases.
        named = ([seed.PROJECT_NAME, seed.REPOSITORY_NAME, seed.INVENTORY_NAME, seed.SSH_KEY_NAME, seed.SUDO_KEY_NAME,
                  seed.ADMIN_NAME] + list(seed.VARIABLE_GROUPS) + [title for title, _names in seed.VIEWS]
                 + [lesson[0] for lesson in seed.LESSONS])
        for name in named:
            self.assertNotRegex(name, r"(?i)practice|\blab\b|lesson")

    def test_every_moved_playbook_keeps_a_thin_file_at_its_earlier_path(self):
        root = Path(__file__).resolve().parents[1]
        for earlier, moved in seed.MOVED_PLAYBOOKS.items():
            with self.subTest(playbook=earlier):
                self.assertTrue((root / moved).is_file())
                (entry,) = yaml.safe_load((root / earlier).read_text())
                # Relative to the earlier file, which is directly in playbooks/.
                self.assertEqual(entry, {"name": "Run the playbook from its folder",
                                         "ansible.builtin.import_playbook": moved.removeprefix("playbooks/")})
        # Nothing else is directly in playbooks/, and every seeded template names a path of today.
        self.assertEqual(sorted(path.name for path in (root / "playbooks").glob("*.yml")),
                         sorted(path.removeprefix("playbooks/") for path in seed.MOVED_PLAYBOOKS))
        for lesson in seed.LESSONS:
            self.assertNotIn(lesson[1], seed.MOVED_PLAYBOOKS)
            self.assertTrue((root / lesson[1]).is_file(), lesson[1])
        self.assertTrue((root / "playbooks" / "site" / "README.md").is_file())

    def test_the_operations_templates_are_scoped_as_their_playbooks_need(self):
        plan = self.plan()
        templates = {t["name"]: t for t in plan["templates"]}
        report, reboot = templates["Health report"], templates["Reboot one target"]
        self.assertEqual((report["playbook"], report["task_params"], json.loads(report["arguments"])),
                         ("playbooks/operations/report.yml", {"limit": ["lab"]}, []))
        self.assertEqual((reboot["playbook"], reboot["task_params"], json.loads(reboot["arguments"])),
                         ("playbooks/operations/reboot.yml", {"limit": [], "allow_override_limit": True}, []))
        self.assertIn("Enter exactly one host in the Limit prompt.", reboot["description"])
        for template in (report, reboot):
            self.assertEqual(template["environment_ids"], [IDS["environments"]["Defaults"]])
        prompt = reboot["survey_vars"][0]
        self.assertEqual((prompt["name"], prompt["type"], prompt["required"]), ("reboot_target_ack", "enum", True))
        self.assertEqual([choice["value"] for choice in prompt["values"]], ["REBOOT NOW"])

    def test_plan_carries_no_private_key_material(self):
        self.assertNotIn("PRIVATE", json.dumps(self.plan()))

    def test_each_system_has_its_own_stig_tab_and_playbooks(self):
        plan = self.plan()
        for label, folder, _group, disa_file in seed.STIG_SYSTEMS:
            with self.subTest(system=label):
                members = dict(seed.VIEWS)[f"STIG · {label}"]
                self.assertTrue(all(name.startswith(f"{label} · STIG ") for name in members))
                self.assertEqual(len(members), 4 if disa_file else 3)
                playbooks = {t["playbook"] for t in plan["templates"] if t["name"] in members}
                self.assertEqual(playbooks, {f"playbooks/stig/{folder}/audit.yml", f"playbooks/stig/{folder}/apply.yml"})
        stig_templates = [t for t in plan["templates"] if "STIG" in t["name"]]
        self.assertTrue(all(t["playbook"].startswith("playbooks/stig/") for t in stig_templates))
        self.assertFalse(set(seed.REPLACED_TEMPLATES) & {t["name"] for t in plan["templates"]})
        self.assertFalse(set(seed.REPLACED_VIEWS) & {title for title, _members in seed.VIEWS})
        self.assertFalse(set(seed.REPLACED_ENVIRONMENTS) & set(seed.VARIABLE_GROUPS))

    def test_disa_templates_audit_their_own_system_with_a_file_in_its_folder(self):
        plan = self.plan()
        scan = (ROOT / "playbooks/tasks/stig_scan.yml").read_text()
        profile_pattern = re.search(r"stig_content_profile \| default\(''\) is match\('([^']+)'\)", scan).group(1)
        for label, folder, _group, disa_file in seed.STIG_SYSTEMS:
            with self.subTest(system=label):
                disa = [t for t in plan["templates"] if t["name"] == f"{label} · STIG audit, DISA SCAP file"]
                if not disa_file:
                    self.assertEqual(disa, [])
                    self.assertNotIn(f"DISA SCAP file · {label}", seed.VARIABLE_GROUPS)
                    continue
                self.assertEqual(disa[0]["playbook"], f"playbooks/stig/{folder}/audit.yml")
                self.assertEqual(disa[0]["environment_ids"], [IDS["environments"][f"DISA SCAP file · {label}"]])
                self.assertEqual(disa[0]["survey_vars"], [])
                values = json.loads(plan["environments"][f"DISA SCAP file · {label}"]["json"])
                self.assertEqual(set(values), {"stig_content_file", "stig_content_profile"})
                # The system's own folder: the playbook scans with the one benchmark it holds,
                # so the seeded value does not go stale with DISA's next release.
                self.assertEqual(values["stig_content_file"], f"content/{folder}")
                self.assertIn("patterns: '*_Benchmark.xml'", scan)
                self.assertRegex(values["stig_content_profile"], profile_pattern)
                self.assertNotIn("REPLACE_WITH", json.dumps(values))

    def test_each_replaced_template_names_the_per_system_templates_that_replace_it(self):
        lessons = {lesson[0]: lesson for lesson in seed.LESSONS}
        self.assertEqual(seed.REPLACED_TEMPLATES, list(seed.REPLACED_BY))
        for old, new in seed.REPLACED_BY.items():
            with self.subTest(old=old):
                successors = seed.successors(old)
                self.assertEqual(successors, [f"{label} · {new}" for label, *_rest in seed.STIG_SYSTEMS
                                              if f"{label} · {new}" in lessons])
                self.assertTrue(successors)
                kind = "audit" if "audit" in old else "apply"
                self.assertTrue(all(lessons[name][1].endswith(f"/{kind}.yml") for name in successors))
                self.assertEqual({lessons[name][3] for name in successors} == {"Allow required reboot"},
                                 "reboot" in old)

    def test_installers_create_a_content_folder_for_each_stig_system(self):
        common = (ROOT / "controller/controller-common.sh").read_text()
        folders = re.search(r"for system in ([^;]+); do", common).group(1).split()
        self.assertEqual(folders, [folder for _label, folder, _group, _file in seed.STIG_SYSTEMS])


if __name__ == "__main__":
    unittest.main()
