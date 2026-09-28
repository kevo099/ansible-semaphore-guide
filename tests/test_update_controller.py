"""Offline checks for updating a seeded controller; nothing here talks to a server."""

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = load("seed-semaphore")
# What the installers of releases before template tabs seeded: eleven templates,
# two variable groups and no tabs.
OLD_TEMPLATES = [lesson[0] for lesson in seed.LESSONS if lesson[0] != "STIG audit, local SCAP content"]


class FakeSemaphore:
    """Records calls and answers like the Semaphore API for one project."""

    def __init__(self, templates, environments=("Practice defaults", "Allow required reboot"), views=()):
        self.calls = []
        self.next_id = 100
        self.environments = [{"id": self.new_id(), "name": name} for name in environments]
        self.views = [{"id": self.new_id(), "title": title, "position": index} for index, title in enumerate(views)]
        self.templates = {}
        for name in templates:
            template_id = self.new_id()
            self.templates[template_id] = {"id": template_id, "name": name, "view_id": None,
                                           "playbook": "kept.yml"}

    def new_id(self):
        self.next_id += 1
        return self.next_id

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if (method, path) == ("GET", "/projects"):
            return [{"id": 1, "name": "Ansible Practice"}]
        if (method, path) == ("GET", "/project/1/repositories"):
            return [{"id": 3, "name": "Local lab folder"}]
        if (method, path) == ("GET", "/project/1/inventory"):
            return [{"id": 4, "name": "Lab inventory file"}]
        if (method, path) == ("GET", "/project/1/environment"):
            return list(self.environments)
        if (method, path) == ("GET", "/project/1/views"):
            return list(self.views)
        if (method, path) == ("GET", "/project/1/templates"):
            return list(self.templates.values())
        if method == "GET" and path.startswith("/project/1/templates/"):
            return dict(self.templates[int(path.rsplit("/", 1)[1])])
        if method == "POST":
            created = {"id": self.new_id(), **body}
            {"/project/1/environment": self.environments, "/project/1/views": self.views}.get(
                path, []).append(created)
            if path == "/project/1/templates":
                self.templates[created["id"]] = created
            return created
        if method == "PUT" and path.startswith("/project/1/templates/"):
            self.templates[int(path.rsplit("/", 1)[1])] = dict(body)
            return None
        raise AssertionError(f"unexpected call {method} {path}")


def run_update(fake, plan=False):
    args = types.SimpleNamespace(project_name="Ansible Practice", plan=plan)
    output = io.StringIO()
    with redirect_stdout(output):
        seed.update(fake, args)
    return json.loads(output.getvalue())


class TemplateTabTests(unittest.TestCase):
    def test_every_seeded_template_has_exactly_one_tab(self):
        names = [name for _title, members in seed.VIEWS for name in members]
        self.assertEqual(sorted(names), sorted(lesson[0] for lesson in seed.LESSONS))
        self.assertEqual(len(names), len(set(names)))

    def test_a_fresh_seed_puts_each_template_on_its_tab(self):
        views = {title: index for index, (title, _members) in enumerate(seed.VIEWS, start=50)}
        ids = {"repository": 3, "inventory": 4, "views": views,
               "environments": {name: 9 for name in seed.VARIABLE_GROUPS}}
        for lesson in seed.LESSONS:
            body = seed.template_payload(1, ids, lesson)
            self.assertEqual(body["view_id"], views[seed.VIEW_OF[lesson[0]]])


class UpdateTests(unittest.TestCase):
    def test_an_old_project_gains_only_what_it_lacks(self):
        fake = FakeSemaphore(OLD_TEMPLATES)
        result = run_update(fake)
        planned = result["done"]
        self.assertEqual(planned["environments"], ["Local SCAP content"])
        self.assertEqual(planned["views"], [title for title, _members in seed.VIEWS])
        self.assertEqual(planned["templates"], ["STIG audit, local SCAP content"])
        self.assertEqual(planned["tabs"], sorted(OLD_TEMPLATES))
        view_ids = {view["title"]: view["id"] for view in fake.views}
        for template in fake.templates.values():
            self.assertEqual(template["view_id"], view_ids[seed.VIEW_OF[template["name"]]], template["name"])
        # Existing templates keep everything else.
        self.assertTrue(all(t["playbook"] == "kept.yml" for t in fake.templates.values()
                            if t["name"] in OLD_TEMPLATES))
        new = next(t for t in fake.templates.values() if t["name"] == "STIG audit, local SCAP content")
        self.assertEqual(new["repository_id"], 3)
        self.assertEqual(new["inventory_id"], 4)

    def test_a_second_update_changes_nothing(self):
        fake = FakeSemaphore(OLD_TEMPLATES)
        run_update(fake)
        fake.calls.clear()
        result = run_update(fake)
        self.assertEqual(result["done"], {"environments": [], "views": [], "templates": [], "tabs": []})
        self.assertTrue(all(method == "GET" for method, _path, _body in fake.calls))

    def test_plan_makes_no_changes(self):
        fake = FakeSemaphore(OLD_TEMPLATES)
        result = run_update(fake, plan=True)
        self.assertEqual(result["planned"]["templates"], ["STIG audit, local SCAP content"])
        self.assertTrue(all(method == "GET" for method, _path, _body in fake.calls))

    def test_a_tab_you_chose_is_kept(self):
        fake = FakeSemaphore(OLD_TEMPLATES, views=("Mine",))
        mine = fake.views[0]["id"]
        ping = next(t for t in fake.templates.values() if t["name"] == "Ping")
        ping["view_id"] = mine
        run_update(fake)
        self.assertEqual(ping["view_id"], mine)
        titles = [view["title"] for view in fake.views]
        self.assertEqual(titles, ["Mine"] + [title for title, _members in seed.VIEWS])
        self.assertEqual([view["position"] for view in fake.views], [0, 1, 2, 3])

    def test_templates_you_added_are_left_alone(self):
        fake = FakeSemaphore(OLD_TEMPLATES + ["My own template"])
        run_update(fake)
        own = next(t for t in fake.templates.values() if t["name"] == "My own template")
        self.assertIsNone(own["view_id"])


class UpdateScriptTests(unittest.TestCase):
    def run_script(self, *arguments):
        return subprocess.run(["/bin/bash", str(ROOT / "scripts" / "update-controller.sh"), *arguments],
                              capture_output=True, text=True, timeout=10)

    def test_help_describes_a_read_only_default(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("read-only plan", result.stdout)

    def test_unknown_arguments_are_refused(self):
        result = self.run_script("--frobnicate")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
