#!/usr/bin/env python3
"""Give Semaphore the lab targets' sudo password: the key "Lab sudo" on the lab inventory.

Run it as root on the controller, in the guide's folder:
    sudo python3.12 controller/lab-sudo.py [--replace] [--lab-dir DIR] [--project-id ID] [--password-stdin]

It does through Semaphore's API on loopback what Stage 4 does in the UI: it stores
the shared sudo password of svc_ansible as the key "Lab sudo", of the type Login
with password and with an empty Username, and chooses that key as the Sudo
Credentials of "Lab inventory file". The Username stays empty because Semaphore
passes it to Ansible as --become-user, the account to become: any name there makes
privileged tasks run as that account instead of root.

Running it again changes nothing. --replace stores a new password in the existing
key. An inventory that uses another sudo credential, a "Lab sudo" of another type,
or one with a Username, is refused with what to do instead; only --replace clears a
Username, by storing the password anew. It asks for the password twice, without
echo, and only when it stores one; --password-stdin reads one line from standard
input instead, for scripts. The password goes only to Semaphore on loopback and is
never printed.
"""

import argparse
import getpass
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


# Run as root from an administrator's copy of the guide: leave no root-owned bytecode in it.
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
MARKER = Path("/etc/semaphore/.practice-project-seeded")
KEY_NAME = "Lab sudo"
# Semaphore's type for Login with password.
KEY_TYPE = "login_password"
# The bootstrap playbook and onboard-linux.sh --ask-password require this length.
MIN_LENGTH = 12
# What must stay as it was when the inventory gets its sudo credential.
INVENTORY_FIELDS = ("name", "type", "inventory", "repository_id", "ssh_key_id", "become_key_id")


def load_seeder():
    spec = importlib.util.spec_from_file_location("seed_semaphore", HERE / "seed-semaphore.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_check(command):
    return subprocess.run(command, capture_output=True, text=True)


def read_password(from_stdin, stdin=None, ask=getpass.getpass, warn=None):
    """The sudo password: asked twice without echo, or one line of standard input."""
    stdin = stdin or sys.stdin
    warn = warn or (lambda message: print(message, file=sys.stderr))
    if from_stdin:
        if stdin.isatty():
            raise SystemExit("--password-stdin reads the password from a pipe, and a terminal would show it; "
                             "leave the option out to be asked without echo. Nothing was changed.")
        line = stdin.readline()
        password = line[:-1] if line.endswith("\n") else line
        password = password[:-1] if password.endswith("\r") else password
    else:
        if not stdin.isatty():
            raise SystemExit("There is no terminal to ask for the sudo password; give it on standard input "
                             "with --password-stdin. Nothing was changed.")
        try:
            password = ask("Sudo password of svc_ansible on the lab targets: ")
            if password:
                again = ask("The same password again: ")
                if again != password:
                    raise SystemExit("The two entries differ; nothing was changed. Run this again.")
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("\nNo password given; nothing was changed.") from None
    if not password:
        raise SystemExit("The password is empty; nothing was changed.")
    if len(password) < MIN_LENGTH:
        warn(f"Warning: the password has fewer than {MIN_LENGTH} characters. The bootstrap playbook and "
             "onboard-linux.sh --ask-password require that many, so they cannot give this password to a target.")
    return password


def key_problems(key):
    """What keeps a key from being the inventory's sudo credential, as readable phrases."""
    problems = []
    if key.get("name") != KEY_NAME:
        problems.append(f"its name is {key.get('name')!r}")
    if key.get("type") != KEY_TYPE:
        problems.append(f"its type is {key.get('type')!r}")
    if (key.get("login_password") or {}).get("login"):
        problems.append("it has a Username")
    # Semaphore marks a key whose secret is missing as empty.
    if key.get("empty"):
        problems.append("it holds no password")
    return problems


class Run:
    """One run against the seeded project that resolve() found."""

    def __init__(self, seeder, client, found, say=print):
        self.seeder, self.client, self.say = seeder, client, say
        self.base, self.project_id = found["base"], found["project"]["id"]
        self.inventory_path = f"{self.base}/inventory/{found['inventory']['id']}"
        self.inventory_name = found["inventory"].get("name") or "Lab inventory file"

    def failed(self, error):
        """Whether Semaphore refused a request (True) or did not answer it (False)."""
        return isinstance(error, self.seeder.ApiError)

    def read_key(self, key_id):
        """The key as Semaphore now describes it, or None if it cannot be read."""
        try:
            key = self.client.call("GET", f"{self.base}/keys/{key_id}")
        except (self.seeder.ApiError, OSError):
            return None
        return key if isinstance(key, dict) else None

    def configure(self, replace, get_password):
        keys = self.seeder.read_list(self.client, f"{self.base}/keys")
        named = [key for key in keys if key.get("name") == KEY_NAME]
        if len(named) > 1:
            ids = ", ".join(str(key.get("id")) for key in named)
            raise SystemExit(f"{len(named)} keys are named {KEY_NAME!r} (IDs {ids}). Rename or delete the extra "
                             "ones in Key Store, then run this again. Nothing was changed.")
        key = named[0] if named else None
        inventory = self.client.call("GET", self.inventory_path)
        become = inventory.get("become_key_id")
        if become and (key is None or become != key.get("id")):
            other = next((k for k in keys if k.get("id") == become), None)
            what = f"the key {other.get('name')!r} (ID {become})" if other else f"the key with ID {become}"
            raise SystemExit(f"{self.inventory_name!r} already uses {what} as its Sudo Credentials, not "
                             f"{KEY_NAME!r}. This script changes only {KEY_NAME!r}: to replace that credential, "
                             f"choose {KEY_NAME!r} under Inventory -> {self.inventory_name} -> Sudo Credentials "
                             "in the UI, or empty that field and run this again. Nothing was changed.")
        if key is not None:
            self.check_existing(key, become, replace)

        if key is None:
            key_id = self.create(get_password())
            self.attach(key_id, f"The key {KEY_NAME!r} (ID {key_id}) was created and is kept; run this again to "
                                "choose it without being asked for the password.")
            self.say(f"Stored the targets' sudo password as the key {KEY_NAME!r} (ID {key_id}), with an empty "
                     f"Username, and chose it as the Sudo Credentials of {self.inventory_name!r}.")
        elif replace:
            self.replace(key, get_password())
            chose = become != key["id"] and self.attach(
                key["id"], f"The new password is stored in {KEY_NAME!r} (ID {key['id']}); run this again to "
                           "choose it without being asked for the password.")
            self.say(f"Stored the new password in the key {KEY_NAME!r} (ID {key['id']}), with an empty Username"
                     + (f", and chose it as the Sudo Credentials of {self.inventory_name!r}." if chose else "."))
        elif become == key["id"]:
            self.say(f"{self.inventory_name!r} already uses the key {KEY_NAME!r} (ID {key['id']}) as its Sudo "
                     "Credentials; nothing changed. To store a new password in it, run this again with --replace.")
            self.say_username_note()
            return 0
        else:
            self.attach(key["id"], f"The key {KEY_NAME!r} (ID {key['id']}) was not changed.")
            self.say(f"Chose the existing key {KEY_NAME!r} (ID {key['id']}) as the Sudo Credentials of "
                     f"{self.inventory_name!r}; the key itself was not changed.")
            self.say_username_note()
        self.say("Next: run the Baseline preview template. Every lab target needs this same sudo password for "
                 "svc_ansible.")
        return 0

    def say_username_note(self):
        # Semaphore keeps a key's Username with its password, encrypted, and never shows it.
        self.say("Semaphore never shows a key's Username. If you typed one when you made the key in the UI, run "
                 "this again with --replace: it stores the password anew with an empty Username.")

    def check_existing(self, key, become, replace):
        """Refuse a "Lab sudo" that cannot be used or fixed from here."""
        if key.get("type") != KEY_TYPE:
            # Semaphore's list of what uses a key leaves out template vaults, so a new type
            # could break something this script cannot see.
            used = (f" First choose no Sudo Credentials for {self.inventory_name!r} under Inventory, since it "
                    "uses that key." if become == key.get("id") else "")
            raise SystemExit(f"The key {KEY_NAME!r} (ID {key.get('id')}) has the type {key.get('type')!r}, not "
                             f"Login with password ({KEY_TYPE}). This script does not change a key's type, which "
                             f"would break whatever else uses it.{used} Rename or delete that key in Key Store, "
                             "then run this again. Nothing was changed.")
        if replace:
            return
        if (key.get("login_password") or {}).get("login"):
            raise SystemExit(f"The key {KEY_NAME!r} (ID {key['id']}) has a Username. Semaphore passes it to "
                             "Ansible as --become-user, so privileged tasks would run as that account instead of "
                             "root. Run this again with --replace to store the password anew with an empty "
                             "Username. Nothing was changed.")
        if key.get("empty"):
            raise SystemExit(f"The key {KEY_NAME!r} (ID {key['id']}) holds no password. Run this again with "
                             "--replace to store one. Nothing was changed.")

    def create(self, password):
        body = {"name": KEY_NAME, "type": KEY_TYPE, "project_id": self.project_id,
                "login_password": {"login": "", "password": password}}
        try:
            created = self.client.call("POST", f"{self.base}/keys", body)
        except (self.seeder.ApiError, OSError) as error:
            if self.failed(error):
                raise SystemExit(f"Semaphore refused to create the key {KEY_NAME!r}: {error}. Nothing was "
                                 "changed.") from None
            raise SystemExit(f"Semaphore did not answer when asked to create the key {KEY_NAME!r} ({error}). "
                             f"Look for it in Key Store: run this again if it is missing, or delete it and run "
                             f"this again. {self.inventory_name!r} was not changed.") from None
        key_id = created.get("id") if isinstance(created, dict) else None
        if not isinstance(key_id, int):
            raise SystemExit(f"Semaphore answered the creation of {KEY_NAME!r} without its ID. Look for it in "
                             f"Key Store, delete it, and run this again. {self.inventory_name!r} was not changed.")
        key = self.read_key(key_id)
        problems = ["it could not be read back"] if key is None else key_problems(key)
        if problems:
            # Nothing uses the new key yet, so it can go again.
            try:
                self.client.call("DELETE", f"{self.base}/keys/{key_id}")
            except (self.seeder.ApiError, OSError) as error:
                raise SystemExit(f"Semaphore did not store the new key {KEY_NAME!r} (ID {key_id}) as asked: "
                                 f"{', '.join(problems)}. Deleting it failed too ({error}): delete key ID "
                                 f"{key_id} in Key Store, then run this again. {self.inventory_name!r} was not "
                                 "changed.") from None
            raise SystemExit(f"Semaphore did not store the new key {KEY_NAME!r} (ID {key_id}) as asked: "
                             f"{', '.join(problems)}. The key was deleted again; nothing was changed.")
        return key_id

    def replace(self, key, password):
        """Store a new password, and an empty Username, in the existing key, as the UI's override does."""
        path = f"{self.base}/keys/{key['id']}"
        current = self.read_key(key["id"]) or key
        body = dict(current, type=KEY_TYPE, override_secret=True, login_password={"login": "", "password": password})
        try:
            self.client.call("PUT", path, body)
        except (self.seeder.ApiError, OSError) as error:
            if self.failed(error):
                raise SystemExit(f"Semaphore refused to store the new password in {KEY_NAME!r} (ID {key['id']}): "
                                 f"{error}. Nothing was changed.") from None
            raise SystemExit(f"Semaphore did not answer when asked to store the new password in {KEY_NAME!r} "
                             f"(ID {key['id']}) ({error}), so it holds the new password or the old one. Run this "
                             f"again with --replace. {self.inventory_name!r} was not changed.") from None
        after = self.read_key(key["id"])
        problems = ["it could not be read back"] if after is None else key_problems(after)
        if problems:
            raise SystemExit(f"Semaphore did not confirm the new password of {KEY_NAME!r} (ID {key['id']}): "
                             f"{', '.join(problems)}. Check the key in Key Store, or run this again with "
                             f"--replace. {self.inventory_name!r} was not changed.")

    def attach(self, key_id, key_state):
        """Choose the key as the inventory's Sudo Credentials and confirm it, or put the inventory back.

        Returns whether the inventory changed; it already had the key when it did not.
        """
        before = self.client.call("GET", self.inventory_path)
        current = before.get("become_key_id")
        if current == key_id:
            return False
        if current:
            raise SystemExit(f"{self.inventory_name!r} got the Sudo Credentials with key ID {current} meanwhile; "
                             f"it was left as it is. {key_state}")
        desired = dict(before, become_key_id=key_id)
        try:
            self.client.call("PUT", self.inventory_path, desired)
        except (self.seeder.ApiError, OSError) as error:
            if self.failed(error):
                raise SystemExit(f"Semaphore refused to choose {KEY_NAME!r} as the Sudo Credentials of "
                                 f"{self.inventory_name!r}: {error}. The inventory was not changed. "
                                 f"{key_state}") from None
            raise SystemExit(f"Semaphore did not answer when asked to choose {KEY_NAME!r} as the Sudo Credentials "
                             f"of {self.inventory_name!r} ({error}); check that inventory in the UI. "
                             f"{key_state}") from None
        after = self.read_inventory()
        if after is not None and all(after.get(field) == desired.get(field) for field in INVENTORY_FIELDS):
            return True
        what = ("it could not be read back" if after is None else "it differs in "
                + ", ".join(field for field in INVENTORY_FIELDS if after.get(field) != desired.get(field)))
        try:
            self.client.call("PUT", self.inventory_path, before)
            restored = self.read_inventory()
            restored = restored is not None and all(restored.get(f) == before.get(f) for f in INVENTORY_FIELDS)
        except (self.seeder.ApiError, OSError):
            restored = False
        if restored:
            raise SystemExit(f"Semaphore did not save {self.inventory_name!r} as asked ({what}); it was put back as "
                             f"it was. {key_state}")
        raise SystemExit(f"Semaphore did not save {self.inventory_name!r} as asked ({what}), and putting it back "
                         f"was not confirmed either; check its settings in the UI. {key_state}")

    def read_inventory(self):
        try:
            inventory = self.client.call("GET", self.inventory_path)
        except (self.seeder.ApiError, OSError):
            return None
        return inventory if isinstance(inventory, dict) else None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--replace", action="store_true",
                        help="store a new password, with an empty Username, in the existing key")
    parser.add_argument("--lab-dir", default="/opt/ansible-lab")
    parser.add_argument("--project-id", type=int, help="the seeded project's ID, when project names repeat")
    parser.add_argument("--password-stdin", action="store_true",
                        help="read the password from one line of standard input instead of asking")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if os.geteuid() != 0:
        raise SystemExit("Run it with sudo on the controller.")
    if not MARKER.exists():
        raise SystemExit("This controller was not set up by an installer that seeds Semaphore; give Semaphore "
                         "the sudo password in the UI, as docs/stage-4-add-target-first-job.md shows.")
    root = Path(os.path.realpath(args.lab_dir))
    if not root.is_dir():
        raise SystemExit(f"No lab folder at {root}; pass the --lab-dir the installer used.")
    if run_check(["systemctl", "is-active", "--quiet", "semaphore"]).returncode != 0:
        raise SystemExit("semaphore.service is not running; start it first.")
    seeder = load_seeder()
    client = seeder.Client(seeder.API, os.environ.get("SEMAPHORE_API_TOKEN") or None)
    seeder.wait_ready(client)
    user = seeder.log_in(client, "admin", ask=True)
    found = seeder.resolve(client, "Ansible Practice", str(root), args.project_id, user)
    seeder.check_access(client, user, found)
    return Run(seeder, client, found).configure(args.replace, lambda: read_password(args.password_stdin))


if __name__ == "__main__":
    sys.exit(main())
