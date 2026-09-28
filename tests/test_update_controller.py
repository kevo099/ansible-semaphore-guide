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
                 views=(), projects=("Ansible Practice",), git_url=LAB, drop_links_on_put=False,
                 fail_put=False):
        self.calls = []
        self.next_id = 100
        self.drop_links_on_put = drop_links_on_put
        self.fail_put = fail_put
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
                "task_params": {"limit": ["lab"]}, "repository_id": 3, "inventory_id": 4}

    def add_template(self, **fields):
        template_id = self.new_id()
        self.templates[template_id] = {"id": template_id, "view_id": None, "environment_ids": [], **fields}
        return self.templates[template_id]

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
            if (self.drop_links_on_put or self.fail_put) and saved.get("view_id"):
                saved["environment_ids"] = []
            self.templates[int(rest.rsplit("/", 1)[1])] = saved
            if self.fail_put and saved.get("view_id"):
                self.fail_put = False
                raise SystemExit(f"PUT {path} failed with HTTP 500")
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
        return plan, seed.apply_update(fake, found, plan, self.backups, say=lambda _text: None)

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
        ping = next(t for t in fake.templates.values() if t["name"] == "Ping")
        ping["view_id"] = fake.views[0]["id"]
        seed.apply_update(fake, found, plan, self.backups, say=lambda _text: None)
        self.assertEqual(ping["view_id"], fake.views[0]["id"])

    def test_a_failed_save_is_put_back_and_leaves_no_pending_record(self):
        fake = FakeSemaphore(fail_put=True)
        with self.assertRaisesRegex(SystemExit, "put back"):
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
        ping = next(t for t in fake.templates.values() if t["name"] == "Ping")
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
