"""Offline checks for controller/lab-sudo.py; the only Semaphore is a stand-in object."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "controller" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = load("seed-semaphore")
lab_sudo = load("lab-sudo")
LAB = "/opt/ansible-lab"
PASSWORD = "correct horse battery"
NEW_PASSWORD = "another long password"
ADMIN_PASSWORD = "installer password"
PERMISSIONS = {"owner": 15, "manager": 5, "task_runner": 1, "guest": 0}


class FakeSemaphore:
    """Answers like the Semaphore 2.19.12 API for keys and inventories, and records every call.

    As in 2.19.12 (api/projects/keys.go, db/AccessKey.go): a key's Username and password
    are its secret, which no GET returns; every key shows an empty login_password, and
    "empty": true when it holds no secret. POST answers the key as GET does. PUT changes
    only the name, unless "override_secret" is set, which also stores the type and the
    new secret. An inventory's PUT stores the whole object. refuse(method, path) may
    answer (status, reason) to make a request fail, and silent(method, path) True to
    leave it unanswered. shows_login makes GET show the stored Username, as a Semaphore
    that did would.
    """

    def __init__(self):
        self.calls = []
        self.next_id = 100
        self.refuse = lambda method, path: None
        self.silent = lambda method, path: False
        self.shows_login = False
        # Called with each stored key or inventory, to make Semaphore save something else.
        self.key_saved = self.inventory_saved = lambda item: None
        self.user = {"id": 1, "username": "admin", "admin": True}
        self.role, self.token, self.session = "owner", None, None
        self.projects = [{"id": 1, "name": "Ansible Practice"}]
        self.repositories = [{"id": 3, "name": "Local lab folder", "git_url": LAB}]
        self.inventory = {"id": 4, "name": "Lab inventory file", "project_id": 1, "type": "file",
                          "inventory": "inventories/lab.ini", "repository_id": 3, "ssh_key_id": 2,
                          "become_key_id": None, "template_id": None}
        self.keys = {1: {"id": 1, "name": "None", "type": "none", "project_id": 1},
                     2: {"id": 2, "name": "Practice target SSH", "type": "ssh", "project_id": 1}}
        self.secrets = {2: {"login": "svc_ansible", "private_key": "-"}}

    def new_id(self):
        self.next_id += 1
        return self.next_id

    def add_key(self, name="Lab sudo", key_type="login_password", login="", password=PASSWORD):
        key_id = self.new_id()
        self.keys[key_id] = {"id": key_id, "name": name, "type": key_type, "project_id": 1}
        if password is not None:
            self.secrets[key_id] = {"login": login, "password": password}
        return key_id

    def view(self, key_id):
        key, secret = self.keys[key_id], self.secrets.get(key_id)
        shown = {**key, "string": "", "ssh": {"login": "", "passphrase": "", "private_key": ""},
                 "login_password": {"login": (secret or {}).get("login", "") if self.shows_login else "",
                                    "password": ""}}
        if not secret and key["type"] != "none":
            shown["empty"] = True
        return shown

    def writes(self):
        return [call for call in self.calls if call[0] != "GET" and call[1] != "/auth/login"]

    def call(self, method, path, body=None):
        self.calls.append((method, path, json.loads(json.dumps(body))))
        refused = self.refuse(method, path)
        if refused:
            raise seed.ApiError(method, path, *refused)
        if self.silent(method, path):
            raise TimeoutError("timed out")
        if path == "/ping":
            return "pong"
        if path == "/auth/login":
            if body != {"auth": self.user["username"], "password": ADMIN_PASSWORD}:
                raise seed.ApiError(method, path, 401)
            self.session = "verified"
            return None
        if path == "/user":
            if self.token == "valid token" or (self.token is None and self.session == "verified"):
                return dict(self.user)
            raise seed.ApiError(method, path, 401)
        if path == "/projects":
            return [dict(p) for p in self.projects]
        match = re.fullmatch(r"/project/1/([a-z]+)(?:/(\d+))?", path)
        if not match:
            raise AssertionError(f"unexpected call {method} {path}")
        kind, number = match.group(1), int(match.group(2)) if match.group(2) else None
        if method == "GET" and number is None:
            if kind == "role":
                return {"role": self.role, "permissions": PERMISSIONS[self.role]}
            if kind == "keys":
                return [self.view(key_id) for key_id in self.keys]
            if kind == "inventory":
                return [dict(self.inventory)]
            return {"repositories": self.repositories, "templates": [], "environment": [], "views": []}[kind]
        if kind == "keys":
            return self.key_call(method, number, body)
        if kind == "inventory" and number == self.inventory["id"]:
            if method == "GET":
                return dict(self.inventory)
            if method == "PUT":
                if body.get("id") != number or body.get("project_id") != 1:
                    raise seed.ApiError(method, path, 400, "Inventory ID in body and URL must be the same")
                self.inventory = dict(body)
                self.inventory_saved(self.inventory)
                return None
        raise AssertionError(f"unexpected call {method} {path}")

    def key_call(self, method, number, body):
        path = f"/project/1/keys/{number}" if number else "/project/1/keys"
        if number is None and method == "POST":
            if body.get("project_id") != 1:
                raise seed.ApiError(method, path, 400, "Project ID in body and URL must be the same")
            key_id = self.add_key(body["name"], body["type"], **body.get("login_password", {}))
            self.key_saved(self.keys[key_id])
            return self.view(key_id)
        if number not in self.keys:
            raise seed.ApiError(method, path, 404)
        if method == "GET":
            return self.view(number)
        if method == "PUT":
            if body.get("id") != number:
                raise seed.ApiError(method, path, 400, "Access key id in URL and in body must be the same")
            self.keys[number]["name"] = body["name"]
            if body.get("override_secret"):
                self.keys[number]["type"] = body["type"]
                self.secrets[number] = dict(body.get("login_password") or {})
            self.key_saved(self.keys[number])
            return None
        if method == "DELETE":
            del self.keys[number]
            self.secrets.pop(number, None)
            return None
        raise AssertionError(f"unexpected call {method} {path}")


class LabSudoTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSemaphore()
        self.said, self.asked = [], 0

    def password(self, value=PASSWORD):
        def give():
            self.asked += 1
            return value
        return give

    def run_tool(self, replace=False, password=PASSWORD):
        """One run; returns the SystemExit message or None. Every message is checked for the password."""
        found = seed.resolve(self.fake, "Ansible Practice", LAB, None, self.fake.user)
        run = lab_sudo.Run(seed, self.fake, found, say=self.said.append)
        try:
            self.assertEqual(run.configure(replace, self.password(password)), 0)
            message = None
        except SystemExit as error:
            message = str(error)
        for text in self.said + [message or ""]:
            self.assertNotIn(password, text)
            self.assertNotIn(PASSWORD, text)
        # The password goes only into a key's body, never into an inventory.
        for _method, path, body in self.fake.calls:
            if "/keys" not in path:
                self.assertNotIn(password, json.dumps(body))
        return message

    def lab_sudo_key(self):
        [key_id] = [key_id for key_id, key in self.fake.keys.items() if key["name"] == "Lab sudo"]
        return key_id

    def assertNothingChanged(self, message, *phrases):
        self.assertIsNotNone(message)
        for phrase in phrases + ("Nothing was changed",):
            self.assertIn(phrase, message)
        self.assertEqual(self.fake.writes(), [])

    def test_a_new_key_with_an_empty_username_is_stored_and_chosen(self):
        self.assertIsNone(self.run_tool())
        key_id = self.lab_sudo_key()
        self.assertEqual(self.fake.writes(), [
            ("POST", "/project/1/keys", {"name": "Lab sudo", "type": "login_password", "project_id": 1,
                                         "login_password": {"login": "", "password": PASSWORD}}),
            ("PUT", "/project/1/inventory/4", self.fake.inventory),
        ])
        self.assertEqual(self.fake.secrets[key_id], {"login": "", "password": PASSWORD})
        self.assertEqual(self.fake.inventory["become_key_id"], key_id)
        self.assertEqual((self.fake.inventory["ssh_key_id"], self.fake.inventory["repository_id"]), (2, 3))
        self.assertEqual(self.asked, 1)
        self.assertEqual(self.said, [
            f"Stored the targets' sudo password as the key 'Lab sudo' (ID {key_id}), with an empty Username, "
            "and chose it as the Sudo Credentials of 'Lab inventory file'.",
            "Next: run the Baseline preview template. Every lab target needs this same sudo password for "
            "svc_ansible."])

    def test_running_it_again_changes_nothing_and_asks_nothing(self):
        self.assertIsNone(self.run_tool())
        key_id, writes = self.lab_sudo_key(), len(self.fake.writes())
        self.said, self.asked = [], 0
        self.assertIsNone(self.run_tool())
        self.assertEqual((len(self.fake.writes()), self.asked), (writes, 0))
        self.assertEqual(self.said[0], f"'Lab inventory file' already uses the key 'Lab sudo' (ID {key_id}) as its "
                                       "Sudo Credentials; nothing changed. To store a new password in it, run this "
                                       "again with --replace.")
        self.assertIn("--replace: it stores the password anew with an empty Username", self.said[1])

    def test_replace_stores_a_new_password_in_the_same_key(self):
        key_id = self.fake.add_key()
        self.fake.inventory["become_key_id"] = key_id
        self.assertIsNone(self.run_tool(replace=True, password=NEW_PASSWORD))
        [(method, path, body)] = self.fake.writes()
        self.assertEqual((method, path), ("PUT", f"/project/1/keys/{key_id}"))
        self.assertEqual((body["id"], body["name"], body["type"], body["override_secret"], body["login_password"]),
                         (key_id, "Lab sudo", "login_password", True, {"login": "", "password": NEW_PASSWORD}))
        self.assertEqual(self.fake.secrets[key_id], {"login": "", "password": NEW_PASSWORD})
        self.assertEqual(self.said[0], f"Stored the new password in the key 'Lab sudo' (ID {key_id}), with an "
                                       "empty Username.")

    def test_an_existing_key_is_chosen_without_asking_for_the_password(self):
        key_id = self.fake.add_key()
        self.assertIsNone(self.run_tool())
        self.assertEqual(self.asked, 0)
        self.assertEqual([call[:2] for call in self.fake.writes()], [("PUT", "/project/1/inventory/4")])
        self.assertEqual(self.fake.inventory["become_key_id"], key_id)
        self.assertEqual(self.fake.secrets[key_id], {"login": "", "password": PASSWORD})
        self.assertEqual(self.said[0], f"Chose the existing key 'Lab sudo' (ID {key_id}) as the Sudo Credentials of "
                                       "'Lab inventory file'; the key itself was not changed.")
        self.assertIn("Semaphore never shows a key's Username", self.said[1])

    def test_replace_also_chooses_a_key_the_inventory_lacks(self):
        key_id = self.fake.add_key()
        self.assertIsNone(self.run_tool(replace=True, password=NEW_PASSWORD))
        self.assertEqual(self.fake.inventory["become_key_id"], key_id)
        self.assertEqual(self.said[0], f"Stored the new password in the key 'Lab sudo' (ID {key_id}), with an "
                                       "empty Username, and chose it as the Sudo Credentials of 'Lab inventory file'.")

    def test_another_sudo_credential_on_the_inventory_is_refused_even_with_replace(self):
        other = self.fake.add_key(name="Vendor sudo")
        self.fake.inventory["become_key_id"] = other
        for replace in (False, True):
            with self.subTest(replace=replace):
                message = self.run_tool(replace=replace)
                self.assertNothingChanged(message, f"'Lab inventory file' already uses the key 'Vendor sudo' (ID {other})")
                self.assertEqual(self.asked, 0)
        self.fake.add_key()
        self.assertNothingChanged(self.run_tool(replace=True), "Vendor sudo")

    def test_a_lab_sudo_of_another_type_is_refused_even_with_replace(self):
        for key_type, attached in (("ssh", False), ("string", True)):
            with self.subTest(key_type=key_type):
                self.fake = FakeSemaphore()
                key_id = self.fake.add_key(key_type=key_type)
                if attached:
                    self.fake.inventory["become_key_id"] = key_id
                for replace in (False, True):
                    message = self.run_tool(replace=replace)
                    self.assertNothingChanged(message, f"has the type {key_type!r}", "Rename or delete that key")
                    self.assertEqual(attached, "First choose no Sudo Credentials" in message)
                self.assertEqual(self.fake.keys[key_id]["type"], key_type)

    def test_a_username_is_refused_and_replace_clears_it(self):
        self.fake.shows_login = True
        key_id = self.fake.add_key(login="svc_ansible")
        self.fake.inventory["become_key_id"] = key_id
        self.assertNothingChanged(self.run_tool(), "has a Username", "--become-user", "--replace")
        self.assertIsNone(self.run_tool(replace=True, password=NEW_PASSWORD))
        self.assertEqual(self.fake.secrets[key_id], {"login": "", "password": NEW_PASSWORD})

    def test_a_key_without_a_password_needs_replace(self):
        key_id = self.fake.add_key(password=None)
        self.assertNothingChanged(self.run_tool(), "holds no password", "--replace")
        self.assertIsNone(self.run_tool(replace=True))
        self.assertEqual(self.fake.secrets[key_id], {"login": "", "password": PASSWORD})
        self.assertEqual(self.fake.inventory["become_key_id"], key_id)

    def test_several_keys_of_that_name_are_refused(self):
        first, second = self.fake.add_key(), self.fake.add_key()
        self.assertNothingChanged(self.run_tool(), f"2 keys are named 'Lab sudo' (IDs {first}, {second})")

    def test_a_refused_creation_changes_nothing(self):
        self.fake.refuse = lambda method, path: (400, "bad key") if method == "POST" else None
        self.assertEqual(self.run_tool(), "Semaphore refused to create the key 'Lab sudo': POST /project/1/keys "
                                          "failed with HTTP 400: bad key. Nothing was changed.")
        self.assertEqual(self.fake.inventory["become_key_id"], None)

    def test_an_unanswered_creation_says_where_to_look(self):
        self.fake.silent = lambda method, path: method == "POST"
        message = self.run_tool()
        self.assertIn("did not answer when asked to create the key 'Lab sudo'", message)
        self.assertIn("'Lab inventory file' was not changed", message)
        self.assertEqual([call[0] for call in self.fake.writes()], ["POST"])

    def test_a_key_stored_otherwise_than_asked_is_deleted_again(self):
        for change, problem in (({"type": "string"}, "its type is 'string'"),
                                ({"name": "Lab sudo copy"}, "its name is 'Lab sudo copy'")):
            with self.subTest(change=change):
                self.fake = FakeSemaphore()
                self.fake.key_saved = lambda key: key.update(change)
                message = self.run_tool()
                self.assertIn(problem, message)
                self.assertIn("The key was deleted again; nothing was changed.", message)
                self.assertEqual(sorted(self.fake.keys), [1, 2])
                self.assertEqual(self.fake.inventory["become_key_id"], None)
        self.fake = FakeSemaphore()
        self.fake.shows_login = True
        self.fake.key_saved = lambda key: self.fake.secrets[key["id"]].update(login="svc_ansible")
        self.assertIn("it has a Username", self.run_tool())
        self.assertEqual(sorted(self.fake.keys), [1, 2])

    def test_a_new_key_that_cannot_be_deleted_again_is_named(self):
        self.fake.key_saved = lambda key: key.update(type="string")
        self.fake.refuse = lambda method, path: (500, "") if method == "DELETE" else None
        message = self.run_tool()
        key_id = self.lab_sudo_key()
        self.assertIn(f"Deleting it failed too (DELETE /project/1/keys/{key_id} failed with HTTP 500): delete key "
                      f"ID {key_id} in Key Store", message)
        self.assertIn("'Lab inventory file' was not changed", message)
        self.assertEqual(self.fake.inventory["become_key_id"], None)

    def test_a_refused_choice_keeps_the_key_and_a_second_run_finishes(self):
        self.fake.refuse = lambda method, path: (400, "no") if (method, path) == ("PUT", "/project/1/inventory/4") else None
        message = self.run_tool()
        key_id = self.lab_sudo_key()
        self.assertIn("Semaphore refused to choose 'Lab sudo' as the Sudo Credentials of 'Lab inventory file'", message)
        self.assertIn(f"The inventory was not changed. The key 'Lab sudo' (ID {key_id}) was created and is kept; run "
                      "this again to choose it without being asked for the password.", message)
        self.fake.refuse = lambda method, path: None
        self.asked = 0
        self.assertIsNone(self.run_tool())
        self.assertEqual((self.asked, self.fake.inventory["become_key_id"]), (0, key_id))

    def test_an_inventory_saved_otherwise_than_asked_is_put_back(self):
        before = dict(self.fake.inventory)
        key_id = self.fake.add_key()
        self.fake.inventory_saved = lambda inventory: inventory.update(ssh_key_id=None) if inventory["become_key_id"] else None
        message = self.run_tool()
        self.assertIn("Semaphore did not save 'Lab inventory file' as asked (it differs in ssh_key_id); it was put back "
                      f"as it was. The key 'Lab sudo' (ID {key_id}) was not changed.", message)
        self.assertEqual(self.fake.inventory, before)

    def test_an_inventory_that_cannot_be_put_back_is_named(self):
        self.fake.add_key()
        self.fake.inventory_saved = lambda inventory: inventory.update(become_key_id=None, ssh_key_id=None)
        message = self.run_tool()
        self.assertIn("(it differs in ssh_key_id, become_key_id), and putting it back was not confirmed either; check "
                      "its settings in the UI.", message)

    def test_a_refused_or_unconfirmed_replacement_is_reported(self):
        key_id = self.fake.add_key()
        self.fake.inventory["become_key_id"] = key_id
        self.fake.refuse = lambda method, path: (500, "") if method == "PUT" else None
        self.assertEqual(self.run_tool(replace=True, password=NEW_PASSWORD),
                         f"Semaphore refused to store the new password in 'Lab sudo' (ID {key_id}): PUT "
                         f"/project/1/keys/{key_id} failed with HTTP 500. Nothing was changed.")
        self.assertEqual(self.fake.secrets[key_id]["password"], PASSWORD)
        self.fake.refuse = lambda method, path: None
        self.fake.silent = lambda method, path: method == "PUT"
        self.assertIn("so it holds the new password or the old one. Run this again with --replace.",
                      self.run_tool(replace=True, password=NEW_PASSWORD))
        self.fake.silent = lambda method, path: False
        self.fake.key_saved = lambda key: self.fake.secrets.pop(key["id"])
        self.assertIn(f"Semaphore did not confirm the new password of 'Lab sudo' (ID {key_id}): it holds no "
                      "password.", self.run_tool(replace=True, password=NEW_PASSWORD))

    def test_a_login_that_may_not_change_the_project_stops_first(self):
        self.fake.user["admin"] = False
        self.fake.role = "task_runner"
        found = seed.resolve(self.fake, "Ansible Practice", LAB, None, self.fake.user)
        with self.assertRaises(SystemExit):
            seed.check_access(self.fake, self.fake.user, found)
        self.assertEqual(self.fake.writes(), [])


class TerminalInput(io.StringIO):
    def __init__(self, text="", terminal=True):
        super().__init__(text)
        self.terminal = terminal

    def isatty(self):
        return self.terminal


class PasswordTests(unittest.TestCase):
    def read(self, from_stdin, stdin, answers=()):
        answers, warnings = list(answers), []

        def ask(prompt):
            self.prompts.append(prompt)
            answer = answers.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        self.prompts = []
        try:
            result = lab_sudo.read_password(from_stdin, stdin, ask, warnings.append)
        except SystemExit as error:
            result = error
        for text in warnings + [str(result) if isinstance(result, SystemExit) else ""]:
            for secret in (PASSWORD, NEW_PASSWORD, "short pass"):
                self.assertNotIn(secret, text)
        return result, warnings

    def test_it_asks_twice_and_takes_matching_entries(self):
        result, warnings = self.read(False, TerminalInput(), [PASSWORD, PASSWORD])
        self.assertEqual((result, warnings), (PASSWORD, []))
        self.assertEqual(self.prompts, ["Sudo password of svc_ansible on the lab targets: ", "The same password again: "])

    def test_differing_empty_and_cancelled_entries_are_refused(self):
        for answers, message in (([PASSWORD, NEW_PASSWORD], "The two entries differ; nothing was changed. Run this again."),
                                 ([""], "The password is empty; nothing was changed."),
                                 ([EOFError()], "\nNo password given; nothing was changed."),
                                 ([PASSWORD, KeyboardInterrupt()], "\nNo password given; nothing was changed.")):
            with self.subTest(message=message):
                result, _warnings = self.read(False, TerminalInput(), answers)
                self.assertIsInstance(result, SystemExit)
                self.assertEqual(str(result), message)
                self.assertNotIn(PASSWORD, str(result))

    def test_a_short_password_is_taken_with_a_warning(self):
        result, warnings = self.read(False, TerminalInput(), ["short pass", "short pass"])
        self.assertEqual(result, "short pass")
        self.assertEqual(len(warnings), 1)
        self.assertIn("fewer than 12 characters", warnings[0])
        self.assertNotIn("short pass", warnings[0])

    def test_standard_input_gives_one_line(self):
        for text in (f"{PASSWORD}\n", f"{PASSWORD}\r\n", PASSWORD, f"{PASSWORD}\nsecond line\n"):
            with self.subTest(text=text):
                result, warnings = self.read(True, TerminalInput(text, terminal=False))
                self.assertEqual((result, warnings, self.prompts), (PASSWORD, [], []))
        result, _warnings = self.read(True, TerminalInput(" spaced password \n", terminal=False))
        self.assertEqual(result, " spaced password ")

    def test_standard_input_must_be_a_pipe_and_hold_a_password(self):
        result, _warnings = self.read(True, TerminalInput(f"{PASSWORD}\n"))
        self.assertIn("--password-stdin reads the password from a pipe", str(result))
        for text in ("", "\n"):
            result, _warnings = self.read(True, TerminalInput(text, terminal=False))
            self.assertEqual(str(result), "The password is empty; nothing was changed.")

    def test_without_a_terminal_it_does_not_ask(self):
        result, _warnings = self.read(False, TerminalInput(f"{PASSWORD}\n", terminal=False))
        self.assertIn("There is no terminal to ask for the sudo password", str(result))
        self.assertEqual(self.prompts, [])


class MainTests(unittest.TestCase):
    """lab-sudo.main() end to end against FakeSemaphore."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        work = Path(directory.name)
        self.marker, self.password_file = work / "seeded", work / "password"
        self.marker.touch()
        self.password_file.write_text(ADMIN_PASSWORD + "\n")
        self.lab = work / "lab"
        self.lab.mkdir()
        self.fake = FakeSemaphore()
        self.fake.repositories[0]["git_url"] = os.path.realpath(self.lab)
        self.service = 0

    def client(self, _base, token=None):
        self.fake.token = token
        return self.fake

    def run_check(self, command):
        self.assertEqual(command, ["systemctl", "is-active", "--quiet", "semaphore"])
        return subprocess.CompletedProcess(command, self.service, "", "")

    def run_main(self, *arguments, stdin="", euid=0):
        output, errors = io.StringIO(), io.StringIO()
        environment = {key: value for key, value in os.environ.items() if key != "SEMAPHORE_API_TOKEN"}
        with contextlib.ExitStack() as stack:
            for patch in (mock.patch.dict(os.environ, environment, clear=True),
                          mock.patch.object(lab_sudo.os, "geteuid", return_value=euid),
                          mock.patch.object(lab_sudo, "MARKER", self.marker),
                          mock.patch.object(lab_sudo, "run_check", self.run_check),
                          mock.patch.object(lab_sudo, "load_seeder", return_value=seed),
                          mock.patch.object(seed, "Client", self.client),
                          mock.patch.object(seed, "PASSWORD_FILE", self.password_file),
                          mock.patch.object(sys, "stdin", TerminalInput(stdin, terminal=False)),
                          contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors)):
                stack.enter_context(patch)
            try:
                result = lab_sudo.main(["--lab-dir", str(self.lab), *arguments])
            except SystemExit as error:
                result = str(error)
        for text in (output.getvalue(), errors.getvalue(), str(result)):
            self.assertNotIn(PASSWORD, text)
        return result, output.getvalue(), errors.getvalue()

    def test_a_password_on_standard_input_is_stored_and_chosen(self):
        result, output, errors = self.run_main("--password-stdin", stdin=f"{PASSWORD}\n")
        self.assertEqual((result, errors), (0, ""))
        key_id = next(k for k, key in self.fake.keys.items() if key["name"] == "Lab sudo")
        self.assertEqual(self.fake.secrets[key_id], {"login": "", "password": PASSWORD})
        self.assertEqual(self.fake.inventory["become_key_id"], key_id)
        self.assertIn("Stored the targets' sudo password as the key 'Lab sudo'", output)

    def test_checks_before_semaphore_is_contacted(self):
        result, _output, _errors = self.run_main("--password-stdin", stdin=f"{PASSWORD}\n", euid=1000)
        self.assertEqual(result, "Run it with sudo on the controller.")
        result, _output, _errors = self.run_main("--lab-dir", str(self.lab / "missing"))
        self.assertTrue(result.startswith("No lab folder at "), result)
        self.service = 3
        result, _output, _errors = self.run_main("--password-stdin", stdin=f"{PASSWORD}\n")
        self.assertEqual(result, "semaphore.service is not running; start it first.")
        self.marker.unlink()
        result, _output, _errors = self.run_main("--password-stdin", stdin=f"{PASSWORD}\n")
        self.assertTrue(result.startswith("This controller was not set up by an installer that seeds"), result)
        self.assertEqual(self.fake.calls, [])

    def test_a_short_password_on_standard_input_is_warned_about(self):
        result, _output, errors = self.run_main("--password-stdin", stdin="short\n")
        self.assertEqual(result, 0)
        self.assertIn("fewer than 12 characters", errors)


if __name__ == "__main__":
    unittest.main()
