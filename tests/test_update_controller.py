"""Offline checks for updating a seeded controller; the only server is a stand-in on loopback."""

import contextlib
import errno
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = load("seed-semaphore")
updater = load("update-controller")
LabFolder = updater.LabFolder
LAB = "/opt/ansible-lab"
LESSON_TEMPLATES = [lesson[0] for lesson in seed.LESSONS if "STIG" not in lesson[0]]
STIG_TEMPLATES = [lesson[0] for lesson in seed.LESSONS if "STIG" in lesson[0]]
# What installers before template tabs seeded: eleven templates, two variable groups, no tabs.
OLD_TEMPLATES = LESSON_TEMPLATES + seed.REPLACED_TEMPLATES[:3]
# What 1.5.0 to 1.6.x seeded: twelve templates on the tabs Lessons, Patching and STIG.
TABBED_VIEWS = {"Lessons": LESSON_TEMPLATES[:5], "Patching": LESSON_TEMPLATES[5:],
                "STIG": seed.REPLACED_TEMPLATES}
# Semaphore's built-in project roles and their permission bits (db/ProjectUser.go).
PERMISSIONS = {"owner": 15, "manager": 5, "task_runner": 1, "guest": 0}
PASSWORD = "installer password"


class FakeSemaphore:
    """Answers like the Semaphore 2.19.12 API for the projects it holds and records every call.

    As in 2.19.12: the template list leaves out vaults, which only GET of one
    template shows; a new project gets the All tab at position 0; the project's
    schedule list holds timed schedules and a template's own list its commit
    checks; deleting a template deletes its schedules and integrations; and a
    password login with a second factor opens a session that GET /user refuses.
    refuse(method, path) may answer (status, reason) to make a request fail.
    """

    def __init__(self, templates=OLD_TEMPLATES, environments=("Practice defaults", "Allow required reboot"),
                 views=(), projects=("Ansible Practice",), git_url=LAB, drop_links_on_put=False,
                 fail_put=False):
        self.calls = []
        self.next_id = 100
        self.drop_links_on_put = drop_links_on_put
        self.fail_put = fail_put
        self.refuse = lambda method, path: None
        self.user = {"id": 1, "username": "admin", "admin": True}
        self.role, self.second_factor, self.token, self.session = "owner", False, None, None
        self.projects, self.keys, self.views, self.schedules, self.integrations = [], [], [], [], []
        for name in projects:
            self.add_project(name)
        self.repositories = [{"id": 3, "name": "Local lab folder", "git_url": git_url}] if projects else []
        self.inventories = ([{"id": 4, "name": "Lab inventory file", "type": "file", "repository_id": 3,
                              "inventory": "inventories/lab.ini"}] if projects else [])
        self.environments = [{"id": self.new_id(), "name": name} for name in environments]
        self.views += [{"id": self.new_id(), "title": title, "position": position} for title, position in views]
        self.templates = {}
        for name in templates:
            template_id = self.new_id()
            self.templates[template_id] = {
                "id": template_id, "name": name, "view_id": None, "playbook": "kept.yml",
                "environment_ids": [self.environments[0]["id"]], "survey_vars": [{"name": "kept"}],
                "task_params": {"limit": ["lab"]}, "repository_id": 3, "inventory_id": 4}

    def add_project(self, name):
        project = {"id": len(self.projects) + 1, "name": name}
        self.projects.append(project)
        # AddProject gives every new project the All tab.
        self.views.append({"id": self.new_id(), "title": "All", "position": 0, "type": "all"})
        return dict(project)

    def add_template(self, **fields):
        template_id = self.new_id()
        self.templates[template_id] = {"id": template_id, "view_id": None, "environment_ids": [], **fields}
        return self.templates[template_id]

    def named(self, name):
        return next(t for t in self.templates.values() if t["name"] == name)

    def add_schedule(self, template_name, name, commit_check=False):
        schedule = {"id": self.new_id(), "project_id": 1, "template_id": self.named(template_name)["id"],
                    "name": name, "cron_format": "0 2 * * *", "type": "", "active": True,
                    "delete_after_run": False, "repository_id": 3 if commit_check else None}
        self.schedules.append(schedule)
        return schedule

    def add_integration(self, template_name, name):
        integration = {"id": self.new_id(), "project_id": 1, "template_id": self.named(template_name)["id"],
                       "name": name, "auth_method": "token", "auth_secret_id": None, "auth_header": "",
                       "searchable": False}
        self.integrations.append(integration)
        return integration

    def store(self, number, body):
        """Save a template as Semaphore does: vaults get IDs and keep only the fields of their type."""
        template = dict(json.loads(json.dumps(body)), id=number)
        vaults = []
        for vault in template.get("vaults") or []:
            vault = dict(vault, id=vault.get("id") or self.new_id(), project_id=1, template_id=number)
            vault.pop({"password": "script", "script": "vault_key_id"}.get(vault.get("type"), ""), None)
            vaults.append(vault)
        template["vaults"] = vaults
        self.templates[number] = template
        return template

    def new_id(self):
        self.next_id += 1
        return self.next_id

    def writes(self):
        return [call for call in self.calls if call[0] != "GET" and call[1] != "/auth/login"]

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        refused = self.refuse(method, path)
        if refused:
            raise seed.ApiError(method, path, *refused)
        if path == "/ping":
            return "pong"
        if path == "/auth/login":
            if body != {"auth": self.user["username"], "password": PASSWORD}:
                raise seed.ApiError(method, path, 401)
            # A login with a second factor opens a session that still waits for its code.
            self.session = "waiting for a second factor" if self.second_factor else "verified"
            return None
        if path == "/user":
            if self.token == "valid token" or (self.token is None and self.session == "verified"):
                return dict(self.user)
            raise seed.ApiError(method, path, 401, "TOTP_REQUIRED" if self.token is None and self.session else "")
        if path == "/projects":
            return self.add_project(body["name"]) if method == "POST" else [dict(p) for p in self.projects]
        match = re.fullmatch(r"/project/\d+/([a-z]+)(?:/(\d+))?(?:/([a-z]+))?", path)
        if not match:
            raise AssertionError(f"unexpected call {method} {path}")
        kind, number, sub = match.group(1), int(match.group(2)) if match.group(2) else None, match.group(3)
        if kind == "role" and method == "GET":
            return {"role": self.role, "permissions": PERMISSIONS[self.role]}
        if kind == "templates":
            return self.template_call(method, path, number, sub, body)
        items = {"keys": self.keys, "repositories": self.repositories, "inventory": self.inventories,
                 "environment": self.environments, "views": self.views, "schedules": self.schedules,
                 "integrations": self.integrations}[kind]
        if method == "GET" and number is None:
            if kind == "schedules":
                return [dict(s, tpl_name=self.templates[s["template_id"]]["name"]) for s in items
                        if s["repository_id"] is None]
            return [dict(item) for item in items]
        if method == "POST" and number is None:
            created = {"id": self.new_id(), **body}
            items.append(created)
            return created
        if method == "DELETE" and number is not None and kind in ("views", "environment"):
            items[:] = [item for item in items if item["id"] != number]
            return None
        raise AssertionError(f"unexpected call {method} {path}")

    def template_call(self, method, path, number, sub, body):
        if number is None and method == "GET":
            return [{key: value for key, value in t.items() if key != "vaults"} for t in self.templates.values()]
        if number is None and method == "POST":
            return self.store(self.new_id(), body)
        if sub == "schedules" and method == "GET":
            return [dict(s) for s in self.schedules if s["template_id"] == number and s["repository_id"] is not None]
        if sub is None and method == "GET":
            template = json.loads(json.dumps(self.templates[number]))
            if not template.get("vaults"):
                template.pop("vaults", None)
            return template
        if sub is None and method == "PUT":
            saved = json.loads(json.dumps(body))
            if (self.drop_links_on_put or self.fail_put) and saved.get("view_id"):
                saved["environment_ids"] = []
            self.store(number, saved)
            if self.fail_put and saved.get("view_id"):
                self.fail_put = False
                raise seed.ApiError(method, path, 500)
            return None
        if sub is None and method == "DELETE":
            del self.templates[number]
            # The database deletes the template's schedules, integrations and tasks with it.
            self.schedules[:] = [s for s in self.schedules if s["template_id"] != number]
            self.integrations[:] = [i for i in self.integrations if i["template_id"] != number]
            return None
        raise AssertionError(f"unexpected call {method} {path}")


def tabbed_project(git_url=LAB):
    """A project as 1.5.0 to 1.6.x seeded it."""
    fake = FakeSemaphore(templates=OLD_TEMPLATES + [seed.REPLACED_TEMPLATES[3]],
                         environments=("Practice defaults", "Allow required reboot", "Local SCAP content"),
                         views=tuple((title, index) for index, title in enumerate(TABBED_VIEWS)), git_url=git_url)
    views = {view["title"]: view["id"] for view in fake.views}
    for template in fake.templates.values():
        template["view_id"] = next(views[title] for title, names in TABBED_VIEWS.items() if template["name"] in names)
        if template["name"] == "STIG audit, local SCAP content":
            template["environment_ids"] = [fake.environments[2]["id"]]
    fake.environments[2].update(json=json.dumps(seed.REPLACED_ENVIRONMENTS["Local SCAP content"]), env="{}")
    return fake


def view_id(fake, title):
    return next(view["id"] for view in fake.views if view["title"] == title)


class SemaphoreUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.backups = Path(self.directory.name) / "backups"

    def update(self, fake, project_id=None, remove_replaced=False):
        found = seed.resolve(fake, "Ansible Practice", LAB, project_id)
        plan = seed.plan_for(found)
        self.said = []
        backup = seed.apply_update(fake, found, plan, self.backups, say=self.said.append)
        if remove_replaced:
            self.removal = seed.remove_replaced(fake, found, plan, self.backups, say=self.said.append)
        return plan, backup

    @staticmethod
    def posted_vaults(fake):
        return [body["vaults"] for method, path, body in fake.calls if method == "POST" and path.endswith("/templates")]

    def test_every_seeded_template_has_exactly_one_tab(self):
        names = [name for _title, members in seed.VIEWS for name in members]
        self.assertEqual(sorted(names), sorted(lesson[0] for lesson in seed.LESSONS))
        self.assertEqual(len(names), len(set(names)))

    def test_a_fresh_seed_puts_each_template_on_its_tab(self):
        views = {title: index for index, (title, _members) in enumerate(seed.VIEWS, start=50)}
        ids = {"repository": 3, "inventory": 4, "views": views,
               "environments": {name: 9 for name in seed.VARIABLE_GROUPS}}
        for lesson in seed.LESSONS:
            self.assertEqual(seed.template_payload(1, ids, lesson)["view_id"], views[seed.VIEW_OF[lesson[0]]])

    def test_an_old_project_gains_only_what_it_lacks_and_keeps_settings(self):
        fake = FakeSemaphore()
        plan, backup = self.update(fake)
        self.assertEqual(plan["environments"], ["DISA SCAP file · RHEL 9", "DISA SCAP file · Ubuntu 24.04"])
        self.assertEqual(plan["views"], [title for title, _members in seed.VIEWS])
        self.assertEqual(plan["templates"], STIG_TEMPLATES)
        self.assertEqual(sorted(t["name"] for t in plan["tabs"]), sorted(LESSON_TEMPLATES))
        self.assertEqual(seed.replaced_names(plan), [f"template {name!r}" for name in sorted(seed.REPLACED_TEMPLATES[:3])])
        view_ids = {view["title"]: view["id"] for view in fake.views}
        # The new tabs follow the All tab that Semaphore gives every project.
        self.assertEqual([view["position"] for view in fake.views], list(range(len(seed.VIEWS) + 1)))
        for template in fake.templates.values():
            self.assertEqual(template["view_id"], view_ids.get(seed.VIEW_OF.get(template["name"])), template["name"])
            if template["name"] in OLD_TEMPLATES:
                self.assertEqual((template["playbook"], template["survey_vars"]), ("kept.yml", [{"name": "kept"}]))
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(len(json.loads(backup.read_text())), len(OLD_TEMPLATES))

    def test_a_second_update_changes_nothing(self):
        fake = FakeSemaphore()
        self.update(fake)
        fake.calls.clear()
        plan, backup = self.update(fake)
        self.assertEqual((plan["environments"], plan["views"], plan["templates"], plan["tabs"]), ([], [], [], []))
        self.assertEqual(fake.writes(), [])
        self.assertIsNone(backup)

    def test_new_tabs_go_after_the_last_existing_position(self):
        fake = FakeSemaphore(views=(("Mine", 5),))
        self.update(fake)
        self.assertEqual([(v["title"], v["position"]) for v in fake.views],
                         [("All", 0), ("Mine", 5)] + [(title, 6 + index) for index, (title, _names) in enumerate(seed.VIEWS)])

    def test_a_tab_you_chose_and_templates_you_added_are_kept(self):
        fake = FakeSemaphore(templates=OLD_TEMPLATES + ["My own"], views=(("Mine", 0),))
        ping = fake.named("Ping")
        ping["view_id"] = view_id(fake, "Mine")
        self.update(fake)
        self.assertEqual(fake.named("Ping")["view_id"], view_id(fake, "Mine"))
        self.assertIsNone(fake.named("My own")["view_id"])

    def test_duplicate_projects_need_an_explicit_id(self):
        fake = FakeSemaphore(projects=("Ansible Practice", "Ansible Practice"))
        with self.assertRaisesRegex(SystemExit, "IDs: 1, 2"):
            self.update(fake)
        self.assertEqual(fake.writes(), [])
        self.update(fake, project_id=2)
        self.assertTrue(all(path.startswith("/project/2/") for _m, path, _b in fake.writes()))

    def test_a_repository_for_another_folder_is_refused(self):
        fake = FakeSemaphore(git_url="/srv/other-lab")
        with self.assertRaisesRegex(SystemExit, "lab folder"):
            self.update(fake)
        self.assertEqual(fake.writes(), [])

    def test_duplicate_tabs_it_needs_stop_before_any_change(self):
        fake = FakeSemaphore(views=(("STIG · RHEL 9", 0), ("STIG · RHEL 9", 1)))
        with self.assertRaisesRegex(SystemExit, "tab 'STIG · RHEL 9'"):
            self.update(fake)
        self.assertEqual(fake.writes(), [])

    def test_a_namesake_of_yours_in_another_repository_is_left_alone(self):
        fake = FakeSemaphore()
        own = fake.add_template(name="Ping", repository_id=444, inventory_id=555, playbook="private/own.yml")
        plan, _backup = self.update(fake)
        self.assertNotIn(own["id"], [t["id"] for t in plan["tabs"]])
        self.assertIsNone(own["view_id"])

    def test_seeded_duplicates_are_reported_and_left_alone(self):
        fake = FakeSemaphore()
        copy = fake.add_template(name="Ping", repository_id=3, inventory_id=4, environment_ids=[1])
        plan, _backup = self.update(fake)
        self.assertEqual(plan["duplicates"], ["Ping"])
        self.assertIsNone(copy["view_id"])

    def test_a_tab_chosen_after_the_plan_is_kept(self):
        fake = FakeSemaphore(views=(("Mine", 0),))
        found = seed.resolve(fake, "Ansible Practice", LAB)
        plan = seed.plan_for(found)
        fake.named("Ping")["view_id"] = view_id(fake, "Mine")
        seed.apply_update(fake, found, plan, self.backups, say=lambda _text: None)
        self.assertEqual(fake.named("Ping")["view_id"], view_id(fake, "Mine"))

    def test_a_failed_save_is_put_back_and_leaves_no_pending_record(self):
        fake = FakeSemaphore(fail_put=True)
        with self.assertRaisesRegex(SystemExit, r"HTTP 500\); its settings were put back"):
            self.update(fake)
        self.assertTrue(all(t["environment_ids"] for t in fake.templates.values() if t["name"] in OLD_TEMPLATES))
        self.assertEqual(seed.pending_edits(self.backups), [])

    def test_an_unconfirmed_edit_blocks_the_next_run_until_checked(self):
        fake = FakeSemaphore()
        self.backups.mkdir(mode=0o700)
        record = self.backups / "pending-template-7.json"
        record.write_text(json.dumps({"id": 7, "name": "Ping"}))
        with self.assertRaisesRegex(SystemExit, "could not confirm"):
            self.update(fake)
        self.assertEqual(fake.writes(), [])
        record.unlink()
        self.update(fake)

    def test_a_template_without_a_variable_group_is_left_as_you_chose(self):
        fake = FakeSemaphore()
        ping = fake.named("Ping")
        ping["environment_ids"] = []
        self.update(fake)
        self.assertEqual(fake.templates[ping["id"]]["environment_ids"], [])

    def test_a_save_that_drops_variable_groups_is_undone_and_stops(self):
        fake = FakeSemaphore(drop_links_on_put=True)
        with self.assertRaisesRegex(SystemExit, "put back"):
            self.update(fake)
        puts = [call for call in fake.writes() if call[0] == "PUT"]
        self.assertEqual(len(puts), 2)
        restored = fake.templates[int(puts[1][1].rsplit("/", 1)[1])]
        self.assertTrue(restored["environment_ids"])
        self.assertIsNone(restored.get("view_id"))

    def test_a_tabbed_project_gains_the_system_tabs_and_keeps_what_they_replace(self):
        fake = tabbed_project()
        plan, backup = self.update(fake)
        self.assertEqual(plan["views"], [title for title, _members in seed.VIEWS[2:]])
        self.assertEqual(plan["templates"], STIG_TEMPLATES)
        self.assertEqual((plan["tabs"], plan["in_use"]), ([], []))
        self.assertIsNone(backup)
        self.assertEqual(seed.replaced_names(plan),
                         [f"template {name!r}" for name in sorted(seed.REPLACED_TEMPLATES)]
                         + ["tab 'STIG'", "variable group 'Local SCAP content'"])
        self.assertFalse([call for call in fake.writes() if call[0] in ("PUT", "DELETE")])
        names = [t["name"] for t in fake.templates.values()]
        self.assertTrue(set(seed.REPLACED_TEMPLATES) <= set(names))
        self.assertEqual(len(names), 4 + len(seed.LESSONS))
        # A later run lists the same replaced objects and adds nothing.
        fake.calls.clear()
        again, _backup = self.update(fake)
        self.assertEqual(again["replaced"], plan["replaced"])
        self.assertEqual(fake.writes(), [])

    def test_remove_replaced_deletes_them_after_a_backup(self):
        fake = tabbed_project()
        plan, backup = self.update(fake, remove_replaced=True)
        self.assertIsNone(backup)
        removal_backup, removed = self.removal
        self.assertEqual(removed, seed.replaced_names(plan))
        deleted = [path for method, path, _body in fake.writes() if method == "DELETE"]
        self.assertEqual(len(deleted), 6)
        # Templates go first, so the tab and the variable group are unused when they go.
        self.assertTrue(all("/templates/" in path for path in deleted[:4]))
        self.assertEqual(sorted(t["name"] for t in fake.templates.values()), sorted(seed.VIEW_OF))
        self.assertEqual([v["title"] for v in fake.views], ["All"] + [title for title, _members in seed.VIEWS])
        self.assertEqual(sorted(e["name"] for e in fake.environments), sorted(seed.VARIABLE_GROUPS))
        saved = json.loads(removal_backup.read_text())
        self.assertTrue(set(OLD_TEMPLATES + [seed.REPLACED_TEMPLATES[3]]) <= {t["name"] for t in saved["templates"]})
        self.assertEqual([v["title"] for v in saved["views"]], ["STIG"])
        self.assertEqual([e["name"] for e in saved["environments"]], ["Local SCAP content"])
        self.assertEqual((saved["schedules"], saved["integrations"]), ([], []))
        self.assertEqual(stat.S_IMODE(removal_backup.stat().st_mode), 0o600)
        fake.calls.clear()
        plan, backup = self.update(fake, remove_replaced=True)
        self.assertEqual((fake.writes(), backup, seed.replaced_names(plan), self.removal), ([], None, [], (None, [])))

    def test_a_replaced_template_that_a_schedule_or_integration_runs_is_kept(self):
        fake = tabbed_project()
        nightly = fake.add_schedule("STIG audit (vendor scan only)", "Nightly audit")
        on_commit = fake.add_schedule("STIG apply, allow required reboot", "", commit_check=True)
        hook = fake.add_integration("STIG apply (vendor fixes, approval required)", "Change ticket")
        plan, _backup = self.update(fake, remove_replaced=True)
        self.assertEqual([t["name"] for t in plan["replaced"]["templates"]], ["STIG audit, local SCAP content"])
        # The kept templates are still on the STIG tab, so it stays too.
        self.assertEqual(plan["replaced"]["views"], [])
        self.assertEqual([e["name"] for e in plan["replaced"]["environments"]], ["Local SCAP content"])
        approval, reboot, audit = seed.in_use_names(plan)
        self.assertIn(f"integration 'Change ticket' (ID {hook['id']}) runs it", approval)
        self.assertIn(f"schedule ID {on_commit['id']} runs it", reboot)
        self.assertIn("such as 'RHEL 9 · STIG apply, allow required reboot'", reboot)
        self.assertTrue(audit.startswith(f"template 'STIG audit (vendor scan only)': schedule 'Nightly audit' "
                                         f"(ID {nightly['id']}) runs it. Move its schedules and integrations to "
                                         "the per-system templates that replace it, such as 'RHEL 9 · STIG audit'"))
        removal_backup, removed = self.removal
        self.assertEqual(removed, ["template 'STIG audit, local SCAP content'", "variable group 'Local SCAP content'"])
        self.assertEqual([line for line in self.said if line.startswith("Kept template")],
                         [f"Kept {line}" for line in (approval, reboot, audit)])
        self.assertEqual((fake.schedules, fake.integrations), ([nightly, on_commit], [hook]))
        saved = json.loads(removal_backup.read_text())
        self.assertEqual(sorted(s["id"] for s in saved["schedules"]), sorted([nightly["id"], on_commit["id"]]))
        self.assertEqual([i["name"] for i in saved["integrations"]], ["Change ticket"])

    def test_a_schedule_added_after_the_plan_keeps_its_template(self):
        fake = tabbed_project()
        found = seed.resolve(fake, "Ansible Practice", LAB)
        plan = seed.plan_for(found)
        self.assertIn("template 'STIG audit (vendor scan only)'", seed.replaced_names(plan))
        late = fake.add_schedule("STIG audit (vendor scan only)", "Added meanwhile")
        said = []
        _backup, removed = seed.remove_replaced(fake, found, plan, self.backups, say=said.append)
        self.assertNotIn("template 'STIG audit (vendor scan only)'", removed)
        self.assertEqual(fake.schedules, [late])
        self.assertTrue(any(line.startswith("Kept template 'STIG audit (vendor scan only)': schedule "
                                            "'Added meanwhile'") for line in said), said)
        self.assertIn("Kept tab 'STIG': other templates are on it", said)

    def test_a_template_whose_schedules_cannot_be_read_is_kept(self):
        fake = tabbed_project()
        fake.refuse = lambda method, path: (404, "") if path.endswith("/integrations") else None
        plan, _backup = self.update(fake, remove_replaced=True)
        self.assertEqual(seed.replaced_names(plan), [])
        lines = seed.in_use_names(plan)
        self.assertEqual(len(lines), 4)
        self.assertTrue(all("could not be read (GET /project/1/integrations failed with HTTP 404)" in line
                            for line in lines), lines)
        self.assertEqual(self.removal, (None, []))
        self.assertFalse([call for call in fake.writes() if call[0] == "DELETE"])

    def test_an_answer_that_is_not_a_list_counts_as_unreadable(self):
        client = types.SimpleNamespace(call=lambda method, path: "<html>Bad gateway</html>")
        with self.assertRaisesRegex(SystemExit, "GET /project/1/schedules did not answer with a list"):
            seed.read_list(client, "/project/1/schedules")
        self.assertEqual(seed.triggers_of(client, "/project/1", [5]),
                         {5: {"error": "GET /project/1/schedules did not answer with a list"}})

    def test_a_replaced_variable_group_you_filled_in_is_kept(self):
        fake = tabbed_project()
        fake.environments[2]["json"] = json.dumps({"stig_content_file": "content/U_RHEL_9_V2R9.xml",
                                                   "stig_content_profile": seed.DISA_PROFILE})
        plan, _backup = self.update(fake, remove_replaced=True)
        self.assertEqual(plan["edited"], ["Local SCAP content"])
        self.assertEqual(plan["replaced"]["environments"], [])
        self.assertIn("Local SCAP content", [e["name"] for e in fake.environments])
        self.assertNotIn("STIG", [v["title"] for v in fake.views])

    def test_new_templates_take_the_vault_password_every_seeded_template_shares(self):
        fake = tabbed_project()
        for template in list(fake.templates.values()):
            fake.store(template["id"], dict(template, vaults=[{"vault_key_id": 77, "type": "password"}]))
        self.update(fake)
        self.assertEqual(self.posted_vaults(fake), [[{"type": "password", "vault_key_id": 77}]] * len(STIG_TEMPLATES))
        self.assertTrue(any("same vault password" in note for note in self.said))

    def test_script_and_named_vaults_are_copied_as_they_are(self):
        cases = {
            "script": [{"type": "script", "script": "scripts/vault-pass.sh"}],
            "named": [{"vault_key_id": 77, "type": "password", "name": "hosts"},
                      {"vault_key_id": 78, "type": "password", "name": "apps"}],
            "mixed": [{"type": "script", "script": "scripts/vault-pass.sh", "name": "apps"},
                      {"vault_key_id": 77, "type": "password", "name": "hosts"}],
        }
        for case, vaults in cases.items():
            with self.subTest(case):
                fake = tabbed_project()
                for template in list(fake.templates.values()):
                    fake.store(template["id"], dict(template, vaults=vaults))
                self.update(fake)
                posted = self.posted_vaults(fake)
                self.assertEqual(len(posted), len(STIG_TEMPLATES))
                for copied in posted:
                    self.assertEqual(sorted(json.dumps(v, sort_keys=True) for v in copied),
                                     sorted(json.dumps(v, sort_keys=True) for v in vaults))

    def test_new_templates_get_no_vault_password_when_the_seeded_ones_differ(self):
        fake = tabbed_project()
        first = next(iter(fake.templates.values()))
        fake.store(first["id"], dict(first, vaults=[{"vault_key_id": 77, "type": "password"}]))
        self.update(fake)
        new = [t for t in fake.templates.values() if t["name"] in STIG_TEMPLATES]
        self.assertTrue(all(t["vaults"] == [] for t in new))
        self.assertTrue(any("different vault passwords" in note for note in self.said))

    def test_vault_passwords_are_read_before_any_change(self):
        fake = tabbed_project()
        fake.refuse = lambda method, path: ((500, "") if method == "GET"
                                            and re.fullmatch(r"/project/1/templates/\d+", path) else None)
        with self.assertRaisesRegex(SystemExit, "HTTP 500"):
            self.update(fake)
        self.assertEqual(fake.writes(), [])

    def test_remove_replaced_keeps_what_your_templates_use(self):
        fake = tabbed_project()
        stig_tab = view_id(fake, "STIG")
        local = fake.environments[2]["id"]
        mine = fake.add_template(name="My scan", repository_id=3, inventory_id=4, view_id=stig_tab,
                                 environment_ids=[local])
        elsewhere = fake.add_template(name="STIG audit (vendor scan only)", repository_id=444, inventory_id=555)
        plan, _backup = self.update(fake, remove_replaced=True)
        self.assertEqual(plan["replaced"]["views"], [])
        self.assertEqual(plan["replaced"]["environments"], [])
        self.assertIn(stig_tab, [v["id"] for v in fake.views])
        self.assertIn(local, [e["id"] for e in fake.environments])
        self.assertIn(mine["id"], fake.templates)
        self.assertIn(elsewhere["id"], fake.templates)
        self.assertEqual(len([path for method, path, _body in fake.writes() if method == "DELETE"]), 4)

    def test_remove_replaced_rechecks_each_object_before_deleting(self):
        fake = tabbed_project()
        found = seed.resolve(fake, "Ansible Practice", LAB)
        plan = seed.plan_for(found)
        renamed = fake.named("STIG audit (vendor scan only)")
        renamed["name"] = "My audit"
        stig_tab = view_id(fake, "STIG")
        local = fake.environments[2]["id"]
        fake.add_template(name="Late", repository_id=3, inventory_id=4, view_id=stig_tab, environment_ids=[local])
        said = []
        seed.remove_replaced(fake, found, plan, self.backups, say=said.append)
        self.assertIn(renamed["id"], fake.templates)
        self.assertIn(stig_tab, [v["id"] for v in fake.views])
        self.assertIn(local, [e["id"] for e in fake.environments])
        self.assertIn("Kept template 'STIG audit (vendor scan only)': it changed since the plan", said)
        self.assertIn("Kept tab 'STIG': other templates are on it", said)


class LoginTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.password_file = Path(directory.name) / "initial-admin-password"
        self.password_file.write_text(PASSWORD + "\n")
        patch = mock.patch.object(seed, "PASSWORD_FILE", self.password_file)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_missing_password_file_without_a_terminal_changes_nothing(self):
        self.password_file.unlink()
        client = seed.Client("http://127.0.0.1:9/api")
        with mock.patch.object(seed.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(SystemExit, "SEMAPHORE_API_TOKEN to an administrator's API token"):
                seed.log_in(client, "admin", ask=True)

    def test_a_password_login_returns_the_user_once_its_session_works(self):
        fake = FakeSemaphore()
        self.assertEqual(seed.log_in(fake, "admin"), fake.user)
        fake.second_factor = True
        with self.assertRaisesRegex(SystemExit, r"accepted, but Semaphore also wants a second factor "
                                                r"\(TOTP_REQUIRED\).*SEMAPHORE_API_TOKEN.*Nothing was changed"):
            seed.log_in(fake, "admin")

    def test_an_api_token_is_checked_and_a_bad_one_explained(self):
        fake = FakeSemaphore()
        fake.token = "valid token"
        self.assertEqual(seed.log_in(fake, "admin")["username"], "admin")
        self.assertNotIn("/auth/login", [path for _method, path, _body in fake.calls])
        fake.token = "expired token"
        with self.assertRaisesRegex(SystemExit, "does not accept SEMAPHORE_API_TOKEN"):
            seed.log_in(fake, "admin")

    def test_only_an_administrator_or_the_projects_owner_or_a_manager_may_update(self):
        fake = FakeSemaphore()
        found = seed.resolve(fake, "Ansible Practice", LAB)
        user = {"username": "ci", "admin": False}
        for role, allowed in (("owner", True), ("manager", True), ("task_runner", False), ("guest", False)):
            with self.subTest(role=role):
                fake.role = role
                if allowed:
                    seed.check_access(fake, user, found)
                else:
                    with self.assertRaisesRegex(SystemExit, f"'ci' may not change the templates.*role: {role}"):
                        seed.check_access(fake, user, found)
        fake.calls.clear()
        seed.check_access(fake, {"username": "admin", "admin": True}, found)
        self.assertEqual(fake.calls, [])

    def test_a_login_that_sees_no_seeded_project_is_told_why(self):
        member = {"id": 2, "username": "learner", "admin": False}
        for user in (member, None):
            with self.subTest(user=user):
                with self.assertRaisesRegex(SystemExit, "found 0 .* sees only the projects it belongs to; use "
                                                        "the login.* If you renamed the project, pass --project-id"):
                    seed.resolve(FakeSemaphore(projects=()), "Ansible Practice", LAB, user=user)
                with self.assertRaisesRegex(SystemExit, "and check --project-id"):
                    seed.resolve(FakeSemaphore(), "Ansible Practice", LAB, project_id=9, user=user)

    def test_an_administrator_without_the_project_is_told_it_was_renamed_or_removed(self):
        # An administrator sees every project, so blaming the login would be wrong.
        admin = FakeSemaphore().user
        with self.assertRaises(SystemExit) as raised:
            seed.resolve(FakeSemaphore(projects=()), "Ansible Practice", LAB, user=admin)
        self.assertIn("No project is named 'Ansible Practice'; if you renamed it, pass --project-id with its ID.",
                      str(raised.exception))
        self.assertNotIn("not a Semaphore administrator", str(raised.exception))
        with self.assertRaisesRegex(SystemExit, "No project has ID 9; check --project-id"):
            seed.resolve(FakeSemaphore(), "Ansible Practice", LAB, project_id=9, user=admin)


class LoopbackSemaphore(http.server.BaseHTTPRequestHandler):
    """Semaphore's login on loopback with an https web_host: a Secure session cookie."""

    second_factor = False

    def log_message(self, *_arguments):
        pass

    def answer(self, status, body=None, cookie=None):
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/api/auth/login":
            return self.answer(400, {"error": "template inventory can not be empty"})
        if body != {"auth": "admin", "password": PASSWORD}:
            return self.answer(401)
        return self.answer(204, cookie="semaphore=session; Path=/; HttpOnly; Secure; SameSite=Lax")

    def do_GET(self):
        if self.path != "/api/user":
            return self.answer(404)
        if "semaphore=session" not in (self.headers.get("Cookie") or ""):
            return self.answer(401)
        if self.second_factor:
            return self.answer(401, {"error": "TOTP_REQUIRED"})
        return self.answer(200, {"id": 1, "username": "admin", "admin": True})


class ClientTests(unittest.TestCase):
    def serve(self, handler=LoopbackSemaphore):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return seed.Client(f"http://127.0.0.1:{server.server_address[1]}/api")

    def log_in(self, client):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        password_file = Path(directory.name) / "initial-admin-password"
        password_file.write_text(PASSWORD + "\n")
        with mock.patch.object(seed, "PASSWORD_FILE", password_file):
            return seed.log_in(client, "admin")

    def test_a_secure_session_cookie_still_comes_back_on_loopback(self):
        self.assertEqual(self.log_in(self.serve())["username"], "admin")

    def test_a_second_factor_is_explained(self):
        client = self.serve(type("SecondFactor", (LoopbackSemaphore,), {"second_factor": True}))
        with self.assertRaisesRegex(SystemExit, r"second factor \(TOTP_REQUIRED\).*SEMAPHORE_API_TOKEN"):
            self.log_in(client)

    def test_semaphores_reason_is_shown_but_never_the_request_body(self):
        with self.assertRaises(SystemExit) as raised:
            self.serve().call("POST", "/project/1/templates", {"name": "Ping", "password": "hunter2"})
        self.assertEqual(str(raised.exception),
                         "POST /project/1/templates failed with HTTP 400: template inventory can not be empty")
        self.assertEqual(raised.exception.status, 400)

    def test_reasons_are_short_printable_text_from_json_only(self):
        self.assertEqual(seed.error_reason(b'{"error": "line one\\nline two \\u001b[31m"}'), "line one line two [31m")
        self.assertEqual(len(seed.error_reason(json.dumps({"error": "x" * 500}).encode())), 200)
        for answer in (b"", b"<html>Bad gateway</html>", b'{"error": 5}', b'["error"]', b"\xff"):
            with self.subTest(answer=answer):
                self.assertEqual(seed.error_reason(answer), "")


class ClassifyTests(unittest.TestCase):
    def test_three_way_decisions(self):
        cases = [
            (b"new", b"old", b"new", "current"),
            (None, None, b"new", "add"),
            (None, b"same", b"same", "removed by you"),
            (None, b"old", b"new", "conflict"),
            (b"old", b"old", b"new", "update"),
            (b"mine", b"old", b"old", "yours"),
            (b"mine", b"old", b"new", "conflict"),
            (b"mine", None, b"new", "conflict"),
            (b"new", None, b"new", "conflict"),
            (b"old", b"old", None, "remove"),
            (b"mine", b"old", None, "conflict"),
            (None, b"old", None, "current"),
        ]
        for lab, base, new, expected in cases:
            with self.subTest(lab=lab, base=base, new=new):
                self.assertEqual(updater.classify(lab, base, new), expected)


def git(folder, *arguments):
    subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@example.test",
                    *arguments], check=True, capture_output=True)


def git_output(folder, *arguments):
    return subprocess.run(["git", "-C", str(folder), *arguments], check=True, capture_output=True,
                          text=True).stdout.strip()


class LabFolderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        work = Path(self.directory.name)
        self.lab_root, self.guide, self.outside = work / "lab", work / "guide", work / "outside"
        for folder in (self.lab_root / "playbooks" / "tasks", self.guide / "playbooks" / "tasks",
                       self.guide / "scripts", self.lab_root / "scripts", self.outside):
            folder.mkdir(parents=True)
        self.files = ["ansible.cfg", "playbooks/keep.yml", "playbooks/stig-audit.yml",
                      "playbooks/tasks/stig_scan.yml", "scripts/summarize_xccdf.py"]
        for relative in self.files:
            (self.lab_root / relative).write_text(f"old {relative}\n")
            (self.guide / relative).write_text(f"old {relative}\n")
        git(self.lab_root, "init", "-q", "-b", "main")
        git(self.lab_root, "add", "-A")
        git(self.lab_root, "commit", "-q", "-m", "Seed the local lab folder from the guide")
        (self.guide / "playbooks/stig-audit.yml").write_text("new audit\n")
        (self.guide / "playbooks/new.yml").write_text("new file\n")
        self.files = sorted(self.files + ["playbooks/new.yml"])
        self.lab = updater.LabFolder(self.lab_root, os.getuid(), os.getgid())
        self.addCleanup(self.lab.close)

    def plan(self, replace_edited=False):
        return updater.lab_plan(self.lab, self.guide, self.files, replace_edited)

    def apply(self, plan, expected):
        changed = []
        for relative in plan["add"] + plan["update"]:
            self.lab.write(relative, (self.guide / relative).read_bytes(), expected[relative])
            changed.append(relative)
        for relative in plan["remove"]:
            self.lab.remove(relative, expected[relative])
            changed.append(relative)
        current = self.lab.read(updater.MANIFEST)
        self.lab.write(updater.MANIFEST, updater.manifest_for(self.guide, self.files, "test"), updater.digest(current))
        git(self.lab_root, "add", "--", *changed, updater.MANIFEST)
        git(self.lab_root, "commit", "-q", "-m", "Update the guide's files to test")

    def write_files(self, plan, expected):
        return updater.write_files(self.lab, self.guide, plan, expected,
                                   updater.manifest_for(self.guide, self.files, "test"))

    def test_a_clean_lab_gets_the_guide_changes(self):
        plan, _expected, problems, source = self.plan()
        self.assertEqual(problems, [])
        self.assertEqual(source, "the installer's commit")
        self.assertEqual(plan["update"], ["playbooks/stig-audit.yml"])
        self.assertEqual(plan["add"], ["playbooks/new.yml"])

    def test_your_edit_survives_a_second_update(self):
        (self.lab_root / "ansible.cfg").write_text("forks = 1\n")
        git(self.lab_root, "commit", "-qam", "My forks")
        plan, expected, problems, _source = self.plan()
        self.assertEqual(problems, [])
        self.apply(plan, expected)
        plan, _expected, problems, source = self.plan()
        self.assertEqual((source, problems, plan["yours"]), (updater.MANIFEST, [], ["ansible.cfg"]))
        self.assertEqual(plan["update"] + plan["add"] + plan["remove"], [])
        (self.guide / "playbooks/keep.yml").write_text("newer\n")
        plan, _expected, _problems, _source = self.plan()
        self.assertEqual((plan["update"], plan["yours"]), (["playbooks/keep.yml"], ["ansible.cfg"]))

    def test_a_history_re_rooted_for_publishing_still_has_the_installers_commit(self):
        (self.lab_root / "ansible.cfg").write_text("forks = 1\n")
        git(self.lab_root, "commit", "-qam", "My forks")
        # The Git migration appendix: publish only the current files, keep the old history locally.
        git(self.lab_root, "checkout", "-q", "--orphan", "publish", "main")
        git(self.lab_root, "commit", "-qm", "Lab playbooks for the private repository")
        git(self.lab_root, "branch", "-m", "main", "local-history")
        git(self.lab_root, "branch", "-m", "publish", "main")
        plan, _expected, problems, source = self.plan()
        self.assertEqual((source, problems), ("the installer's commit", []))
        self.assertEqual((plan["update"], plan["add"], plan["yours"], plan["conflict"]),
                         (["playbooks/stig-audit.yml"], ["playbooks/new.yml"], ["ansible.cfg"], []))
        # Without that branch no record is left, and every existing guide file counts as changed by both.
        git(self.lab_root, "branch", "-q", "-D", "local-history")
        plan, _expected, problems, source = self.plan()
        self.assertIsNone(source)
        self.assertEqual(plan["conflict"], [f for f in self.files if f != "playbooks/new.yml"])

    def test_a_release_that_drops_or_renames_a_file(self):
        plan, expected, _problems, _source = self.plan()
        self.apply(plan, expected)
        (self.guide / "playbooks/keep.yml").rename(self.guide / "playbooks/kept.yml")
        self.files = [f if f != "playbooks/keep.yml" else "playbooks/kept.yml" for f in self.files]
        plan, expected, problems, _source = self.plan()
        self.assertEqual(problems, [])
        self.assertEqual((plan["remove"], plan["add"]), (["playbooks/keep.yml"], ["playbooks/kept.yml"]))
        self.apply(plan, expected)
        self.assertFalse((self.lab_root / "playbooks/keep.yml").exists())
        self.assertNotIn("playbooks/keep.yml", json.loads((self.lab_root / updater.MANIFEST).read_text())["files"])

    def test_an_edited_file_the_release_drops_is_a_conflict(self):
        plan, expected, _problems, _source = self.plan()
        self.apply(plan, expected)
        (self.lab_root / "playbooks/keep.yml").write_text("mine\n")
        git(self.lab_root, "commit", "-qam", "Mine")
        (self.guide / "playbooks/keep.yml").unlink()
        self.files.remove("playbooks/keep.yml")
        plan, _expected, problems, _source = self.plan()
        self.assertEqual(plan["conflict"], ["playbooks/keep.yml"])
        self.assertTrue(problems)

    def test_a_file_of_yours_where_the_release_adds_one_stays_yours(self):
        (self.lab_root / "playbooks/new.yml").write_text("new file\n")
        git(self.lab_root, "add", "playbooks/new.yml")
        git(self.lab_root, "commit", "-qm", "My new.yml, same bytes")
        plan, _expected, problems, _source = self.plan()
        self.assertEqual(plan["conflict"], ["playbooks/new.yml"])
        self.assertTrue(problems)

    def test_a_removed_record_stops_instead_of_guessing(self):
        plan, expected, _problems, _source = self.plan()
        self.apply(plan, expected)
        git(self.lab_root, "rm", "-q", updater.MANIFEST)
        git(self.lab_root, "commit", "-qm", "Drop the record")
        _plan, _expected, problems, _source = self.plan()
        self.assertTrue(any("was removed in commit" in problem and "git checkout" in problem for problem in problems))

    def test_a_file_both_changed_stops_unless_replacement_is_asked_for(self):
        (self.lab_root / "playbooks/stig-audit.yml").write_text("my audit\n")
        git(self.lab_root, "commit", "-qam", "My audit")
        plan, _expected, problems, _source = self.plan()
        self.assertEqual(plan["conflict"], ["playbooks/stig-audit.yml"])
        self.assertTrue(any("both" in problem for problem in problems))
        plan, _expected, problems, _source = self.plan(replace_edited=True)
        self.assertEqual(problems, [])
        self.assertIn("playbooks/stig-audit.yml", plan["update"])

    def test_uncommitted_staged_ignored_and_deleted_changes_are_problems(self):
        scenarios = {
            "modified": lambda: (self.lab_root / "playbooks/keep.yml").write_text("edited\n"),
            "deleted": lambda: (self.lab_root / "ansible.cfg").unlink(),
            "untracked": lambda: (self.lab_root / "playbooks/new.yml").write_text("mine\n"),
            "ignored": lambda: ((self.lab_root / ".gitignore").write_text("playbooks/new.yml\n"),
                                (self.lab_root / "playbooks/new.yml").write_text("mine\n")),
        }
        for name, change in scenarios.items():
            with self.subTest(name):
                git(self.lab_root, "reset", "-q", "--hard")
                git(self.lab_root, "clean", "-qfdx")
                change()
                _plan, _expected, problems, _source = self.plan()
                self.assertTrue(problems, name)
        git(self.lab_root, "reset", "-q", "--hard")
        git(self.lab_root, "clean", "-qfdx")
        (self.lab_root / "notes.txt").write_text("unrelated\n")
        git(self.lab_root, "add", "notes.txt")
        _plan, _expected, problems, _source = self.plan()
        self.assertTrue(any("staged" in problem for problem in problems))

    def test_uncommitted_files_say_whether_to_commit_or_discard_them(self):
        plan, expected, _problems, _source = self.plan()
        self.write_files(plan, expected)
        # The record is there: an update wrote everything and stopped before its commit.
        _plan, _expected, problems, _source = self.plan()
        self.assertEqual(len(problems), 3)
        self.assertTrue(all("commit the files it wrote, .guide-files.json included" in p for p in problems), problems)
        git(self.lab_root, "reset", "-q", "--hard")
        git(self.lab_root, "clean", "-qfd")
        (self.lab_root / "playbooks/new.yml").write_text("new file\n")
        _plan, _expected, problems, _source = self.plan()
        self.assertEqual(problems[0], "uncommitted change to a guide file: ?? playbooks/new.yml (commit your own "
                                      "edit; discard what an interrupted update wrote, with git checkout -- FILE, "
                                      "or by deleting a file Git does not track)")

    def test_a_write_that_stops_part_way_puts_back_what_it_wrote(self):
        (self.guide / "ansible.cfg").write_text("new cfg\n")
        real_write = LabFolder.write
        for stop, message in ((OSError(errno.ENOSPC, "No space left on device"), r"\[Errno 28\] No space left on device"),
                              (KeyboardInterrupt(), "it was interrupted")):
            with self.subTest(message):
                plan, expected, problems, _source = self.plan()
                self.assertEqual((problems, plan["add"] + plan["update"]),
                                 ([], ["playbooks/new.yml", "ansible.cfg", "playbooks/stig-audit.yml"]))

                def stop_at_the_third(folder, relative, data, expected_hash, stop=stop):
                    if relative == "playbooks/stig-audit.yml":
                        raise stop
                    return real_write(folder, relative, data, expected_hash)

                with mock.patch.object(LabFolder, "write", stop_at_the_third):
                    with self.assertRaisesRegex(SystemExit, f"stopped: {message}\\. The files written were put "
                                                            "back, so nothing in the folder was changed"):
                        self.write_files(plan, expected)
                self.assertEqual(git_output(self.lab_root, "status", "--porcelain", "--untracked-files=all"), "")
                self.assertEqual((self.lab_root / "ansible.cfg").read_text(), "old ansible.cfg\n")
                self.assertEqual(self.plan()[0], plan)
        changed = self.write_files(*self.plan()[:2])
        self.assertEqual(changed, ["playbooks/new.yml", "ansible.cfg", "playbooks/stig-audit.yml", updater.MANIFEST])

    def test_a_file_saved_while_the_update_writes_is_left_and_named(self):
        (self.guide / "ansible.cfg").write_text("new cfg\n")
        plan, expected, _problems, _source = self.plan()
        real_write = LabFolder.write

        def save_then_fill_the_disk(folder, relative, data, expected_hash):
            if relative == "playbooks/stig-audit.yml":
                (self.lab_root / "ansible.cfg").write_text("saved meanwhile\n")
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_write(folder, relative, data, expected_hash)

        with mock.patch.object(LabFolder, "write", save_then_fill_the_disk):
            with self.assertRaisesRegex(SystemExit, "except these, which changed meanwhile or could not be put "
                                                    "back: ansible.cfg. Semaphore is updated. Check them with git "
                                                    "status and git diff in "):
                self.write_files(plan, expected)
        self.assertEqual((self.lab_root / "ansible.cfg").read_text(), "saved meanwhile\n")
        self.assertFalse((self.lab_root / "playbooks/new.yml").exists())

    def test_a_file_edited_after_the_plan_is_not_overwritten(self):
        plan, expected, _problems, _source = self.plan()
        (self.lab_root / "playbooks/stig-audit.yml").write_text("typed meanwhile\n")
        with self.assertRaises(updater.Unsafe):
            self.lab.write("playbooks/stig-audit.yml", b"guide\n", expected["playbooks/stig-audit.yml"])
        self.assertEqual((self.lab_root / "playbooks/stig-audit.yml").read_text(), "typed meanwhile\n")
        (self.lab_root / "playbooks/new.yml").write_text("appeared meanwhile\n")
        with self.assertRaises(updater.Unsafe):
            self.lab.write("playbooks/new.yml", b"guide\n", None)
        self.assertEqual((self.lab_root / "playbooks/new.yml").read_text(), "appeared meanwhile\n")

    def test_a_missing_git_email_is_filled_in_before_any_change(self):
        isolated = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        with mock.patch.dict(os.environ, isolated):
            git(self.lab_root, "config", "user.useConfigOnly", "true")
            git(self.lab_root, "config", "user.name", "Only A Name")
            self.assertEqual(updater.commit_identity(self.lab), updater.FALLBACK_IDENTITY)
            git(self.lab_root, "config", "user.email", "me@example.test")
            self.assertEqual(updater.commit_identity(self.lab), [])

    def test_a_save_during_the_swap_is_swapped_back(self):
        plan, expected, _problems, _source = self.plan()
        target = self.lab_root / "playbooks/stig-audit.yml"
        planned = target.read_bytes()
        target.write_text("saved during the swap\n")
        real_read = updater.LabFolder._read_at
        calls = []

        def read_once_as_planned(fd, leaf, relative):
            calls.append(leaf)
            return planned if len(calls) == 1 else real_read(fd, leaf, relative)

        with mock.patch.object(updater.LabFolder, "_read_at", staticmethod(read_once_as_planned)):
            with self.assertRaisesRegex(updater.Unsafe, "your version was kept"):
                self.lab.write("playbooks/stig-audit.yml", b"guide\n", expected["playbooks/stig-audit.yml"])
        self.assertEqual(target.read_text(), "saved during the swap\n")
        self.assertEqual(sorted(p.name for p in target.parent.iterdir() if p.name.startswith(".")), [])

    def test_a_reverted_update_says_how_to_apply_it_again(self):
        plan, expected, _problems, _source = self.plan()
        self.apply(plan, expected)
        git(self.lab_root, "revert", "--no-edit", "HEAD")
        _plan, _expected, problems, _source = self.plan()
        self.assertTrue(any("was reverted" in problem and "git revert" in problem for problem in problems))

    def test_an_uncommitted_record_deletion_says_to_check_it_out(self):
        plan, expected, _problems, _source = self.plan()
        self.apply(plan, expected)
        (self.lab_root / updater.MANIFEST).unlink()
        _plan, _expected, problems, _source = self.plan()
        self.assertTrue(any(f"git checkout HEAD -- {updater.MANIFEST}" in problem for problem in problems))

    def test_writes_are_atomic_owned_and_leave_no_temporary_files(self):
        self.lab.write("playbooks/deeper/new.yml", b"data\n", None)
        written = self.lab_root / "playbooks/deeper/new.yml"
        self.assertEqual(written.read_bytes(), b"data\n")
        self.assertEqual(stat.S_IMODE(written.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(written.parent.stat().st_mode), 0o2750)
        self.assertEqual([p.name for p in written.parent.iterdir()], ["new.yml"])

    def test_a_swapped_root_path_does_not_redirect_writes(self):
        moved, decoy = self.lab_root.with_name("moved-lab"), self.outside / "lab"
        (decoy / "playbooks").mkdir(parents=True)
        self.lab_root.rename(moved)
        self.lab_root.symlink_to(decoy)
        self.lab.write("playbooks/new.yml", b"guide\n", None)
        self.assertEqual((moved / "playbooks/new.yml").read_bytes(), b"guide\n")
        self.assertFalse((decoy / "playbooks/new.yml").exists())
        self.assertFalse(self.lab.same_folder())
        with self.assertRaises(SystemExit):
            self.lab.git("status")

    def test_links_in_the_lab_are_refused_and_never_followed(self):
        target = self.outside / "private.yml"
        target.write_text("private\n")
        target.chmod(0o600)
        link = self.lab_root / "playbooks/keep.yml"
        link.unlink()
        link.symlink_to(target)
        with self.assertRaises(updater.Unsafe):
            self.lab.read("playbooks/keep.yml")
        (self.lab_root / "content").symlink_to(self.outside)
        with self.assertRaises(updater.Unsafe):
            self.lab.folder_state("content")
        tasks = self.lab_root / "playbooks/tasks"
        for child in tasks.iterdir():
            child.unlink()
        tasks.rmdir()
        tasks.symlink_to(self.outside)
        with self.assertRaises(updater.Unsafe):
            self.lab.write("playbooks/tasks/stig_scan.yml", b"guide\n", None)
        self.assertEqual(target.read_text(), "private\n")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["private.yml"])


@unittest.skipIf(os.geteuid() == 0, "the updater refuses a lab folder that root owns")
class UpdaterMainTests(unittest.TestCase):
    """update-controller.main() end to end, against FakeSemaphore and a lab folder in a temporary directory."""

    # This release's guide files, and what an earlier installer copied into the lab folder.
    RELEASE = {"ansible.cfg": "[defaults]\nforks = 5\n", "playbooks/ping.yml": "ping\n",
               "playbooks/stig/rhel/9/audit.yml": "audit\n", "scripts/summarize_xccdf.py": "summary\n"}
    EARLIER = {"ansible.cfg": "[defaults]\n", "playbooks/ping.yml": "ping\n", "scripts/summarize_xccdf.py": "summary\n"}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        work = Path(os.path.realpath(self.directory.name))
        self.guide, self.lab_root = work / "guide", work / "lab"
        for folder, files in ((self.guide, self.RELEASE), (self.lab_root, self.EARLIER)):
            for relative, text in files.items():
                (folder / relative).parent.mkdir(parents=True, exist_ok=True)
                (folder / relative).write_text(text)
        git(self.lab_root, "init", "-q", "-b", "main")
        git(self.lab_root, "add", "-A")
        git(self.lab_root, "commit", "-q", "-m", "Seed the local lab folder from the guide")
        self.marker, self.password_file, self.backups = work / "seeded", work / "password", work / "backups"
        self.marker.touch()
        self.password_file.write_text(PASSWORD + "\n")
        self.fake = tabbed_project(git_url=str(self.lab_root))
        self.output = io.StringIO()

    def client(self, _base, token=None):
        self.fake.token = token
        return self.fake

    def lab_folder(self, root, uid, gid, _git_prefix):
        # Git runs as the test's own user instead of through runuser.
        self.folders.append(LabFolder(root, uid, gid))
        return self.folders[-1]

    @staticmethod
    def run_check(command):
        if command[0] in ("systemctl", "runuser"):
            return subprocess.CompletedProcess(command, 0, "", "")
        if "describe" in command:
            return subprocess.CompletedProcess(command, 0, "v9.9.9\n", "")
        if command[0] == "python3.12":
            return subprocess.CompletedProcess(command, 0, json.dumps({"checks": {"http_ping": True}}), "")
        return subprocess.CompletedProcess(command, 1, "", "")

    def run_main(self, *arguments, lab_dir=None, token=None):
        self.output, self.folders, self.removals = io.StringIO(), [], 0
        environment = {key: value for key, value in os.environ.items() if key != "SEMAPHORE_API_TOKEN"}
        environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                           **({"SEMAPHORE_API_TOKEN": token} if token else {}))
        argv = ["update-controller.py", "--lab-dir", str(lab_dir or self.lab_root), *arguments]
        real_remove = seed.remove_replaced

        def remove_after_commit(*positional, **keywords):
            # The templates a release replaced go only once the lab folder holds that
            # release's files, committed: until then they are what still works.
            self.assertEqual(git_output(self.lab_root, "status", "--porcelain", "--untracked-files=all"), "")
            self.assertEqual(git_output(self.lab_root, "log", "-1", "--format=%s"),
                             "Update the guide's files to v9.9.9")
            for relative, text in self.RELEASE.items():
                self.assertEqual((self.lab_root / relative).read_text(), text)
            self.removals += 1
            return real_remove(*positional, **keywords)

        with contextlib.ExitStack() as stack:
            # The folder and its lock last as long as the run, as when the process exits.
            stack.callback(lambda: [folder.close() for folder in self.folders])
            for patch in (mock.patch.object(sys, "argv", argv),
                          mock.patch.dict(os.environ, environment, clear=True),
                          mock.patch.object(updater.os, "geteuid", return_value=0),
                          mock.patch.object(updater, "MARKER", self.marker),
                          mock.patch.object(updater, "REPO", self.guide),
                          mock.patch.object(updater, "run_check", self.run_check),
                          mock.patch.object(updater.grp, "getgrnam",
                                            return_value=types.SimpleNamespace(gr_gid=os.getgid())),
                          mock.patch.object(updater, "LabFolder", self.lab_folder),
                          mock.patch.object(updater, "load_seeder", return_value=seed),
                          mock.patch.object(seed, "Client", self.client),
                          mock.patch.object(seed, "BACKUP_DIR", self.backups),
                          mock.patch.object(seed, "PASSWORD_FILE", self.password_file),
                          mock.patch.object(seed, "remove_replaced", remove_after_commit),
                          contextlib.redirect_stdout(self.output)):
                stack.enter_context(patch)
            return updater.main()

    def test_an_update_writes_commits_and_seeds_and_a_second_run_has_nothing_to_do(self):
        nightly = self.fake.add_schedule("STIG audit (vendor scan only)", "Nightly audit")
        self.assertEqual(self.run_main("--apply", "--remove-replaced"), 0, self.output.getvalue())
        out = self.output.getvalue()
        self.assertEqual(git_output(self.lab_root, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(git_output(self.lab_root, "log", "-1", "--format=%s"), "Update the guide's files to v9.9.9")
        for relative, text in self.RELEASE.items():
            self.assertEqual((self.lab_root / relative).read_text(), text)
        self.assertEqual(json.loads((self.lab_root / updater.MANIFEST).read_text())["guide"], "v9.9.9")
        self.assertTrue((self.lab_root / "content/rhel/9").is_dir())
        self.assertEqual(sorted(t["name"] for t in self.fake.templates.values()),
                         sorted(list(seed.VIEW_OF) + ["STIG audit (vendor scan only)"]))
        self.assertEqual(self.fake.schedules, [nightly])
        self.assertIn("Kept template 'STIG audit (vendor scan only)': schedule 'Nightly audit'", out)
        self.assertIn("Removed 4 replaced object(s) from Semaphore.", out)
        self.assertEqual(self.removals, 1)
        self.assertIn("The readiness check passed.", out)
        self.assertEqual(self.run_main(), 0, self.output.getvalue())
        out = self.output.getvalue()
        for line in ("Files to add: 0", "Files to update (only the guide changed them): 0", "Template tabs to add: 0",
                     "Templates to add: 0", "Replaced templates that schedules or integrations run, kept until you "
                     "move those: 1", "Plan only. Run again with --apply to make these changes."):
            self.assertIn(line, out)

    def test_a_plan_with_problems_says_so_and_exits_with_1(self):
        (self.lab_root / "playbooks/ping.yml").write_text("edited, not committed\n")
        self.assertEqual(self.run_main(), 1)
        out = self.output.getvalue()
        self.assertIn("Problem: uncommitted change to a guide file:  M playbooks/ping.yml", out)
        self.assertIn("Plan only. Resolve the 1 problem(s) above before you run it with --apply.", out)
        self.assertEqual(self.fake.writes(), [])

    def test_without_the_installers_commit_every_existing_guide_file_counts_as_changed_by_both(self):
        git(self.lab_root, "commit", "-q", "--amend", "-m", "Another first commit")
        self.assertEqual(self.run_main(), 1)
        out = self.output.getvalue()
        self.assertIn("No record of the guide's earlier files was found, so every existing guide file counts as "
                      "changed by both.", out)
        self.assertIn("Files that both you and this release changed or claim: 3", out)

    def test_a_missing_lab_folder_is_named(self):
        with self.assertRaisesRegex(SystemExit, r"No lab folder at .*/no-such-lab; pass the --lab-dir the "
                                                r"installer used\."):
            self.run_main(lab_dir=self.lab_root.parent / "no-such-lab")

    def test_a_write_that_fails_part_way_leaves_the_folder_as_it_was(self):
        real_write = LabFolder.write

        def full_disk(folder, relative, data, expected):
            if relative == "ansible.cfg":
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_write(folder, relative, data, expected)

        old_stig = [t["name"] for t in self.fake.templates.values() if t["name"].startswith("STIG ")]
        self.assertEqual(len(old_stig), 4)
        with mock.patch.object(LabFolder, "write", full_disk):
            with self.assertRaisesRegex(SystemExit, "No space left on device. The files written were put back, so "
                                                    "nothing in the folder was changed; Semaphore is updated."):
                self.run_main("--apply", "--remove-replaced")
        self.assertEqual(git_output(self.lab_root, "status", "--porcelain", "--untracked-files=all"), "")
        # The replaced templates stay while the folder still holds the files they use.
        self.assertEqual(self.removals, 0)
        self.assertEqual([call for call in self.fake.writes() if call[0] == "DELETE"], [])
        names = [t["name"] for t in self.fake.templates.values()]
        self.assertTrue(all(name in names for name in old_stig), names)
        self.assertEqual(self.run_main("--apply"), 0, self.output.getvalue())
        self.assertEqual(git_output(self.lab_root, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertIn("Templates to add: 0", self.output.getvalue())

    def test_a_token_whose_user_may_not_change_the_project_stops_before_any_change(self):
        self.fake.user.update(username="ci-runner", admin=False)
        self.fake.role = "task_runner"
        with self.assertRaisesRegex(SystemExit, "'ci-runner' may not change the templates.*role: task_runner"):
            self.run_main("--apply", token="valid token")
        self.assertEqual(self.fake.writes(), [])
        self.assertEqual(git_output(self.lab_root, "status", "--porcelain", "--untracked-files=all"), "")


class SeedMainTests(unittest.TestCase):
    """seed-semaphore.py main() against FakeSemaphore: a fresh seed, then an update of it."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        work = Path(self.directory.name)
        self.lab = work / "lab"
        (self.lab / "inventories").mkdir(parents=True)
        (self.lab / "inventories/lab.ini").write_text("[lab:children]\n")
        self.key, self.known_hosts = work / "svc_ansible", work / "known_hosts"
        # Split, so the repository's check for key material does not match this stand-in.
        header = "OPENSSH " + "PRIVATE KEY-----"
        self.key.write_text(f"-----BEGIN {header}\nnot a real key\n-----END {header}\n")
        self.known_hosts.write_text("")
        self.marker, self.password_file = work / "seeded", work / "password"
        self.password_file.write_text(PASSWORD + "\n")
        self.fake = FakeSemaphore(templates=(), environments=(), projects=())
        self.output = io.StringIO()

    def client(self, _base, token=None):
        self.fake.token = token
        return self.fake

    def run_main(self, *arguments, token=None):
        self.output = io.StringIO()
        environment = {key: value for key, value in os.environ.items() if key != "SEMAPHORE_API_TOKEN"}
        environment.update({"SEMAPHORE_API_TOKEN": token} if token else {})
        argv = ["seed-semaphore.py", "--lab-dir", str(self.lab), *arguments]
        with contextlib.ExitStack() as stack:
            for patch in (mock.patch.object(sys, "argv", argv),
                          mock.patch.dict(os.environ, environment, clear=True),
                          mock.patch.object(seed, "MARKER", self.marker),
                          mock.patch.object(seed, "Client", self.client),
                          mock.patch.object(seed, "PASSWORD_FILE", self.password_file),
                          mock.patch.object(seed, "BACKUP_DIR", Path(self.directory.name) / "backups"),
                          mock.patch.object(seed.sys.stdin, "isatty", return_value=False),
                          contextlib.redirect_stdout(self.output)):
                stack.enter_context(patch)
            return seed.main()

    def seed(self, token=None):
        return self.run_main("--key-file", str(self.key), "--known-hosts", str(self.known_hosts), token=token)

    def test_a_fresh_seed_puts_each_template_on_its_tab_and_is_up_to_date(self):
        self.assertEqual(self.seed(), 0)
        self.assertTrue(self.marker.exists())
        views = {view["title"]: view for view in self.fake.views}
        self.assertEqual(sorted(views), sorted(["All"] + [title for title, _names in seed.VIEWS]))
        self.assertEqual(sorted(t["name"] for t in self.fake.templates.values()), sorted(seed.VIEW_OF))
        for template in self.fake.templates.values():
            self.assertEqual(template["view_id"], views[seed.VIEW_OF[template["name"]]]["id"], template["name"])
        self.assertEqual(len(json.loads(self.output.getvalue())["templates"]), len(seed.LESSONS))
        self.assertEqual(self.run_main("--update", "--plan"), 0)
        planned = json.loads(self.output.getvalue())["planned"]
        self.assertEqual([planned[key] for key in ("environments", "views", "templates", "tabs", "in_use", "edited")],
                         [[]] * 6)
        self.assertEqual(seed.replaced_names(planned), [])

    def test_seeding_needs_an_administrator_and_otherwise_changes_nothing(self):
        self.fake.user.update(username="someone", admin=False)
        with self.assertRaisesRegex(SystemExit, "'someone' is not an administrator; seeding needs"):
            self.seed(token="valid token")
        self.assertEqual((self.fake.writes(), self.marker.exists()), ([], False))

    def test_seeding_takes_an_api_token_when_the_password_no_longer_works(self):
        self.password_file.write_text("changed in the UI\n")
        with self.assertRaisesRegex(SystemExit, "or set SEMAPHORE_API_TOKEN"):
            self.seed()
        self.assertEqual(self.fake.writes(), [])
        self.assertEqual(self.seed(token="valid token"), 0)
        self.assertTrue(self.marker.exists())

    def test_a_seed_that_fails_part_way_shows_semaphores_reason_and_leaves_no_marker(self):
        posted = []

        def refuse_the_third_template(method, path):
            if method == "POST" and path.endswith("/templates"):
                posted.append(path)
                if len(posted) == 3:
                    return 400, "template inventory can not be empty"
            return None

        self.fake.refuse = refuse_the_third_template
        with self.assertRaisesRegex(SystemExit, "^POST /project/1/templates failed with HTTP 400: template "
                                                "inventory can not be empty$"):
            self.seed()
        self.assertFalse(self.marker.exists())


class ReadinessTests(unittest.TestCase):
    def test_only_new_failures_are_errors(self):
        nginx = "nginx_listens_only_where_expected"
        cases = [
            ([], [], ("passed", [])),
            ([nginx], [nginx], ("unchanged", [nginx])),
            ([nginx, "x"], [nginx], ("unchanged", [nginx])),
            ([], ["x"], ("new", ["x"])),
            ([nginx], [nginx, "x"], ("new", ["x"])),
        ]
        for before, after, expected in cases:
            with self.subTest(before=before, after=after):
                self.assertEqual(updater.readiness_outcome(before, after), expected)

    def test_known_failures_come_with_their_fix(self):
        self.assertIn("expose-semaphore.sh --mode https", updater.readiness_hint("nginx_listens_only_where_expected"))
        self.assertIn("chmod 0640", updater.readiness_hint("service_can_read_known_hosts"))
        self.assertEqual(updater.readiness_hint("semaphore_bind_matches_exposure_https"), updater.EXPOSURE_HINT)
        self.assertIn("check-controller.py", updater.readiness_hint("http_ping"))

    def test_the_report_is_read_from_the_check_output(self):
        report = json.dumps({"passed": False, "checks": {"http_ping": True, "port_443_listening": False}})
        with mock.patch.object(updater, "run_check",
                               return_value=subprocess.CompletedProcess([], 1, stdout=report, stderr="")):
            self.assertEqual(updater.failing_readiness(), ["port_443_listening"])
        with mock.patch.object(updater, "run_check",
                               return_value=subprocess.CompletedProcess([], 1, stdout="Traceback", stderr="")):
            self.assertEqual(updater.failing_readiness(), ["readiness_check_did_not_report"])


class UpdateScriptTests(unittest.TestCase):
    def run_script(self, *arguments):
        return subprocess.run(["/bin/bash", str(ROOT / "scripts" / "update-controller.sh"), *arguments],
                              capture_output=True, text=True, timeout=10)

    def test_help_describes_a_read_only_default(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("read-only plan", result.stdout)
        self.assertIn("exits with status 1 when it lists problems", result.stdout)

    def test_unknown_arguments_are_refused(self):
        self.assertEqual(self.run_script("--frobnicate").returncode, 2)

    def test_the_wrapper_passes_every_option_the_updater_defines(self):
        options = set(re.findall(r'add_argument\("(--[a-z-]+)"', (ROOT / "scripts" / "update-controller.py").read_text()))
        wrapper = (ROOT / "scripts" / "update-controller.sh").read_text()
        accepted = set(re.search(r"\n    (--plan\|[^)]*)\) ;;", wrapper).group(1).split("|"))
        self.assertTrue(options)
        self.assertLessEqual(options, accepted)
        usage = self.run_script("--help").stdout
        for option in options:
            with self.subTest(option=option):
                self.assertIn(option, usage)


if __name__ == "__main__":
    unittest.main()
