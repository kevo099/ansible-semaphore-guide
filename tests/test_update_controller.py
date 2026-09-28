"""Offline checks for updating a seeded controller; nothing here talks to a server."""

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
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
LAB = "/opt/ansible-lab"
# What installers before template tabs seeded: eleven templates, two variable groups, no tabs.
OLD_TEMPLATES = [lesson[0] for lesson in seed.LESSONS if lesson[0] != "STIG audit, local SCAP content"]


class FakeSemaphore:
    """Answers like the Semaphore API for the projects it holds and records every call."""

    def __init__(self, templates=OLD_TEMPLATES, environments=("Practice defaults", "Allow required reboot"),
                 views=(), projects=("Ansible Practice",), git_url=LAB, drop_links_on_put=False):
        self.calls = []
        self.next_id = 100
        self.drop_links_on_put = drop_links_on_put
        self.projects = [{"id": index + 1, "name": name} for index, name in enumerate(projects)]
        self.repositories = [{"id": 3, "name": "Local lab folder", "git_url": git_url}]
        self.inventories = [{"id": 4, "name": "Lab inventory file", "type": "file", "repository_id": 3,
                             "inventory": "inventories/lab.ini"}]
        self.environments = [{"id": self.new_id(), "name": name} for name in environments]
        self.views = [{"id": self.new_id(), "title": title, "position": position} for title, position in views]
        self.templates = {}
        for name in templates:
            template_id = self.new_id()
            self.templates[template_id] = {
                "id": template_id, "name": name, "view_id": None, "playbook": "kept.yml",
                "environment_ids": [self.environments[0]["id"]], "survey_vars": [{"name": "kept"}],
                "task_params": {"limit": ["lab"]}}

    def new_id(self):
        self.next_id += 1
        return self.next_id

    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        project, rest = None, path
        if path.startswith("/project/"):
            project, _, rest = path[len("/project/"):].partition("/")
            rest = "/" + rest
        if path == "/projects":
            return list(self.projects)
        answers = {"/repositories": self.repositories, "/inventory": self.inventories,
                   "/environment": self.environments, "/views": self.views,
                   "/templates": list(self.templates.values())}
        if method == "GET" and rest in answers:
            return [dict(item) for item in answers[rest]]
        if method == "GET" and rest.startswith("/templates/"):
            return json.loads(json.dumps(self.templates[int(rest.rsplit("/", 1)[1])]))
        if method == "POST":
            created = {"id": self.new_id(), **body}
            if rest == "/templates":
                self.templates[created["id"]] = created
            else:
                {"/environment": self.environments, "/views": self.views}[rest].append(created)
            return created
        if method == "PUT" and rest.startswith("/templates/"):
            saved = json.loads(json.dumps(body))
            if self.drop_links_on_put and saved.get("view_id"):
                saved["environment_ids"] = []
            self.templates[int(rest.rsplit("/", 1)[1])] = saved
            return None
        raise AssertionError(f"unexpected call {method} {path}")


class SemaphoreUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.backups = Path(self.directory.name) / "backups"

    def update(self, fake, project_id=None):
        found = seed.resolve(fake, "Ansible Practice", LAB, project_id)
        plan = seed.plan_for(found)
        return plan, seed.apply_update(fake, found, plan, self.backups)

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
        self.assertEqual(plan["environments"], ["Local SCAP content"])
        self.assertEqual(plan["views"], [title for title, _members in seed.VIEWS])
        self.assertEqual(plan["templates"], ["STIG audit, local SCAP content"])
        self.assertEqual(sorted(t["name"] for t in plan["tabs"]), sorted(OLD_TEMPLATES))
        view_ids = {view["title"]: view["id"] for view in fake.views}
        self.assertEqual([view["position"] for view in fake.views], [0, 1, 2])
        for template in fake.templates.values():
            self.assertEqual(template["view_id"], view_ids[seed.VIEW_OF[template["name"]]], template["name"])
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
                         [("Mine", 5), ("Lessons", 6), ("Patching", 7), ("STIG", 8)])

    def test_a_tab_you_chose_and_templates_you_added_are_kept(self):
        fake = FakeSemaphore(templates=OLD_TEMPLATES + ["My own"], views=(("Mine", 0),))
        ping = next(t for t in fake.templates.values() if t["name"] == "Ping")
        ping["view_id"] = fake.views[0]["id"]
        self.update(fake)
        self.assertEqual(ping["view_id"], fake.views[0]["id"])
        own = next(t for t in fake.templates.values() if t["name"] == "My own")
        self.assertIsNone(own["view_id"])

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
        fake = FakeSemaphore(views=(("STIG", 0), ("STIG", 1)))
        with self.assertRaisesRegex(SystemExit, "tab 'STIG'"):
            self.update(fake)
        self.assertEqual(fake.writes(), [])

    def test_a_save_that_drops_variable_groups_is_undone_and_stops(self):
        fake = FakeSemaphore(drop_links_on_put=True)
        with self.assertRaisesRegex(SystemExit, "restored"):
            self.update(fake)
        puts = [call for call in fake.writes() if call[0] == "PUT"]
        self.assertEqual(len(puts), 2)
        restored = fake.templates[int(puts[1][1].rsplit("/", 1)[1])]
        self.assertTrue(restored["environment_ids"])
        self.assertIsNone(restored.get("view_id"))

    def test_a_missing_password_file_without_a_terminal_changes_nothing(self):
        client = seed.Client("http://127.0.0.1:9/api")
        with mock.patch.object(seed.Path, "read_text", side_effect=FileNotFoundError), \
             mock.patch.object(seed.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(SystemExit, "SEMAPHORE_API_TOKEN"):
                seed.log_in(client, "admin", ask=True)


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
        ]
        for lab, base, new, expected in cases:
            with self.subTest(lab=lab, base=base, new=new):
                self.assertEqual(updater.classify(lab, base, new), expected)


def git(folder, *arguments):
    subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@example.test",
                    *arguments], check=True, capture_output=True)


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

    def plan(self, replace_edited=False):
        return updater.lab_plan(self.lab, self.guide, self.files, replace_edited)

    def test_a_clean_lab_gets_the_guide_changes(self):
        plan, problems, base = self.plan()
        self.assertEqual(problems, [])
        self.assertTrue(base)
        self.assertEqual(plan["update"], ["playbooks/stig-audit.yml"])
        self.assertEqual(plan["add"], ["playbooks/new.yml"])

    def test_your_committed_edit_is_kept_when_the_guide_did_not_change_the_file(self):
        (self.lab_root / "ansible.cfg").write_text("forks = 1\n")
        git(self.lab_root, "commit", "-qam", "My forks")
        plan, problems, _base = self.plan()
        self.assertEqual(problems, [])
        self.assertIn("ansible.cfg", plan["yours"])

    def apply(self, plan):
        written = plan["add"] + plan["update"]
        for relative in written:
            self.lab.write(relative, (self.guide / relative).read_bytes())
        self.lab.write(updater.MANIFEST, updater.manifest_for(self.guide, self.files, "test"))
        git(self.lab_root, "add", "--", *written, updater.MANIFEST)
        git(self.lab_root, "commit", "-q", "-m", "Update the guide's files to test")

    def test_your_edit_survives_a_second_update(self):
        (self.lab_root / "ansible.cfg").write_text("forks = 1\n")
        git(self.lab_root, "commit", "-qam", "My forks")
        plan, problems, _source = self.plan()
        self.assertEqual(problems, [])
        self.apply(plan)
        plan, problems, source = self.plan()
        self.assertEqual(source, updater.MANIFEST)
        self.assertEqual(problems, [])
        self.assertEqual(plan["yours"], ["ansible.cfg"])
        self.assertEqual(plan["update"] + plan["add"], [])
        # A later guide change to a file you left alone is still delivered.
        (self.guide / "playbooks/keep.yml").write_text("newer\n")
        plan, problems, _source = self.plan()
        self.assertEqual(plan["update"], ["playbooks/keep.yml"])
        self.assertEqual(plan["yours"], ["ansible.cfg"])

    def test_a_file_both_changed_stops_unless_replacement_is_asked_for(self):
        (self.lab_root / "playbooks/stig-audit.yml").write_text("my audit\n")
        git(self.lab_root, "commit", "-qam", "My audit")
        plan, problems, _base = self.plan()
        self.assertEqual(plan["conflict"], ["playbooks/stig-audit.yml"])
        self.assertTrue(any("both" in problem for problem in problems))
        plan, problems, _base = self.plan(replace_edited=True)
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
                _plan, problems, _base = self.plan()
                self.assertTrue(problems, name)
        git(self.lab_root, "reset", "-q", "--hard")
        git(self.lab_root, "clean", "-qfdx")
        (self.lab_root / "notes.txt").write_text("unrelated\n")
        git(self.lab_root, "add", "notes.txt")
        _plan, problems, _base = self.plan()
        self.assertTrue(any("staged" in problem for problem in problems))

    def test_writes_are_atomic_owned_and_leave_no_temporary_files(self):
        self.lab.write("playbooks/deeper/new.yml", b"data\n")
        written = self.lab_root / "playbooks/deeper/new.yml"
        self.assertEqual(written.read_bytes(), b"data\n")
        self.assertEqual(stat.S_IMODE(written.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(written.parent.stat().st_mode), 0o2750)
        self.assertEqual([p.name for p in written.parent.iterdir()], ["new.yml"])

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
            self.lab.write("playbooks/tasks/stig_scan.yml", b"guide\n")
        self.assertEqual(target.read_text(), "private\n")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["private.yml"])


class UpdateScriptTests(unittest.TestCase):
    def run_script(self, *arguments):
        return subprocess.run(["/bin/bash", str(ROOT / "scripts" / "update-controller.sh"), *arguments],
                              capture_output=True, text=True, timeout=10)

    def test_help_describes_a_read_only_default(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("read-only plan", result.stdout)

    def test_unknown_arguments_are_refused(self):
        self.assertEqual(self.run_script("--frobnicate").returncode, 2)


if __name__ == "__main__":
    unittest.main()
