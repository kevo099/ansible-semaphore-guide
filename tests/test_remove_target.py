"""Offline runs of controller/remove-target.sh on a temporary lab folder; nothing here contacts a host."""

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "controller" / "remove-target.sh"
# Documentation addresses (RFC 5737), built in parts so the publication check accepts them.
TEST_NET = ".".join(("192", "0", "2"))
ALMA, UBUNTU = f"{TEST_NET}.12", f"{TEST_NET}.11"
INVENTORY = f"""# Local lab inventory read by Semaphore at every run.
[ubuntu]
lab-ubuntu ansible_host={UBUNTU}

[enterprise_linux]
lab-alma ansible_host={ALMA}

[lab:children]
ubuntu
enterprise_linux

[lab:vars]
ansible_user=svc_ansible
ansible_python_interpreter=/usr/bin/python3
"""
WITHOUT_ALMA = INVENTORY.replace(f"lab-alma ansible_host={ALMA}\n", "")
HINT = ("Only the controller changed: lab-alma itself still has the svc_ansible account, its authorized keys, "
        "its sudo rule and its SSH drop-in.\n")


@unittest.skipUnless(shutil.which("ssh-keygen") and shutil.which("flock"), "needs ssh-keygen and flock")
class RemoveTargetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.lab = self.work / "lab"
        self.inventories = self.lab / "inventories"
        self.inventories.mkdir(parents=True)
        self.inventory = self.inventories / "lab.ini"
        self.inventory.write_text(INVENTORY)
        # known-hosts sits in its own folder, as /etc/semaphore does, so a test sees every file left there.
        self.etc = self.work / "etc"
        self.etc.mkdir()
        self.known_hosts = self.etc / "known_hosts"
        self.alma_key, self.ubuntu_key = self.make_key("alma"), self.make_key("ubuntu")
        self.known_hosts.write_text(f"{UBUNTU} {self.ubuntu_key['line']}\n{ALMA} {self.alma_key['line']}\n")
        # The service reads both files through its group: keep a mode the script's umask would not give.
        for path in (self.inventory, self.known_hosts):
            path.chmod(0o640)
        # Root is a stand-in; ssh-keygen is the real one, slowed by $KEYGEN_DELAY seconds so
        # that two runs would overlap without turns.
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.stub("id", 'echo "${FAKE_UID:-0}"')
        # What changes in the lab folder is done as its owner: runuser -u OWNER -- COMMAND.
        self.owner_calls = self.work / "owner-calls"
        self.stub("runuser", f'echo "$2 $4" >> {self.owner_calls}\nshift 3\nexec "$@"')
        self.stub("ssh-keygen", f'sleep "${{KEYGEN_DELAY:-0}}"\nexec {shutil.which("ssh-keygen")} "$@"')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    def make_key(self, name):
        path = self.work / name
        subprocess.run(["ssh-keygen", "-q", "-t", "rsa", "-b", "2048", "-N", "", "-f", str(path)], check=True)
        public = Path(f"{path}.pub").read_text().split()
        fingerprint = subprocess.run(["ssh-keygen", "-lf", f"{path}.pub"], capture_output=True, text=True,
                                     check=True).stdout.split()[1]
        return {"line": f"{public[0]} {public[1]}", "fingerprint": fingerprint}

    def command(self, name="lab-alma", *options):
        return ["bash", str(SCRIPT), "--name", name, *options, "--lab-dir", str(self.lab),
                "--known-hosts", str(self.known_hosts)]

    def environment(self, **extra):
        return dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", **extra)

    def remove(self, name="lab-alma", *options, **extra):
        return subprocess.run(self.command(name, *options), capture_output=True, text=True,
                              env=self.environment(**extra), timeout=60)

    def state(self):
        return self.inventory.read_text(), self.known_hosts.read_text()

    def backups(self):
        return sorted(self.inventories.glob("lab.ini.before-remove-*.bak"))

    def leftovers(self):
        """Every file besides the two the script edits and the copies it keeps."""
        return sorted(str(p.relative_to(self.work)) for folder in (self.inventories, self.etc)
                      for p in folder.iterdir() if p not in (self.inventory, self.known_hosts)
                      and p not in self.backups())

    def assertUnchanged(self, result, returncode, before=None):
        self.assertEqual(result.returncode, returncode, result.stdout + result.stderr)
        self.assertEqual(self.state(), before or (INVENTORY, f"{UBUNTU} {self.ubuntu_key['line']}\n"
                                                             f"{ALMA} {self.alma_key['line']}\n"))
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.leftovers(), [])

    def test_the_line_and_its_key_are_removed_and_the_old_inventory_kept(self):
        before = self.state()
        result = self.remove()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state(), (WITHOUT_ALMA, f"{UBUNTU} {self.ubuntu_key['line']}\n"))
        [backup] = self.backups()
        self.assertEqual(backup.read_text(), before[0])
        self.assertRegex(backup.name, r"^lab\.ini\.before-remove-lab-alma\.\d{8}T\d{6}\.bak$")
        self.assertEqual(result.stdout, (
            f"Removed lab-alma ansible_host={ALMA} from {self.inventory}; the inventory as it was is in {backup}.\n"
            f"Removed 1 trusted host key line(s) for {ALMA} from {self.known_hosts}:\n"
            f"  {self.alma_key['fingerprint']} (RSA)\n" + HINT))
        # No .old copy as ssh-keygen -R leaves, and no temporary file.
        self.assertEqual(self.leftovers(), [])

    def test_the_lab_folder_is_changed_as_its_owner_and_never_as_root(self):
        # The folder is its editor's, who could swap a name in it for a link between two steps.
        self.assertEqual(self.remove().returncode, 0)
        owner = self.inventories.owner()
        calls = [line.split() for line in self.owner_calls.read_text().splitlines()]
        self.assertEqual({user for user, _ in calls}, {owner})
        self.assertEqual([command for _, command in calls], ["mktemp", "sh", "chgrp", "chmod", "cp", "mv"])
        # Nothing else in the script creates, copies, moves or removes a file of that folder.
        script = SCRIPT.read_text()
        for line in script.splitlines():
            if any(name in line for name in ('"$new_inventory"', '"$backup"')) and \
                    any(f" {tool} " in f" {line}" for tool in ("rm", "mv", "cp", "chown", "chmod", "chgrp", "chcon", ">")):
                with self.subTest(line=line.strip()):
                    self.assertTrue("in_lab " in line or line.lstrip().startswith(("[[", "if [[", "echo")), line)

    def test_a_failed_run_removes_its_files_as_the_owner_too(self):
        self.stub("mv", "exit 1")
        result = self.remove("lab-alma", "--keep-key")
        self.assertUnchanged(result, 1)
        calls = [line.split()[1] for line in self.owner_calls.read_text().splitlines()]
        self.assertEqual(calls[-2:], ["rm", "rm"])
        self.assertEqual((self.backups(), self.leftovers()), ([], []))

    def test_variables_kept_for_the_name_are_named(self):
        folder = self.inventories / "host_vars"
        folder.mkdir()
        (folder / "lab-alma.yml").write_text("ansible_port: 2222\n")
        (folder / "lab-ubuntu.yml").write_text("ansible_port: 2222\n")
        result = self.remove()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Kept the variables of lab-alma, which a later host of that name would get: {folder}/lab-alma.yml\n",
                      result.stdout)
        self.assertNotIn("lab-ubuntu.yml", result.stdout)
        self.assertTrue((folder / "lab-alma.yml").exists())

    def test_owner_group_and_mode_are_kept_and_the_files_replaced_whole(self):
        # Without root the test can only give the files groups it belongs to; a second one,
        # if this account has one, shows the group is copied rather than defaulted.
        group = next((g for g in os.getgroups() if g != os.getgid()), os.getgid())
        for path in (self.inventory, self.known_hosts):
            os.chown(path, -1, group)
        before = {path: os.stat(path) for path in (self.inventory, self.known_hosts)}
        self.assertEqual(self.remove().returncode, 0)
        for path, old in before.items():
            new = os.stat(path)
            with self.subTest(path=path.name):
                self.assertEqual((new.st_uid, new.st_gid, stat.S_IMODE(new.st_mode)),
                                 (old.st_uid, group, 0o640))
                self.assertNotEqual(new.st_ino, old.st_ino)
        [backup] = self.backups()
        copy = os.stat(backup)
        self.assertEqual((copy.st_uid, copy.st_gid, stat.S_IMODE(copy.st_mode)), (os.getuid(), group, 0o640))

    def test_running_it_again_changes_nothing_and_keeps_no_further_copy(self):
        self.assertEqual(self.remove().returncode, 0)
        after, backups = self.state(), self.backups()
        result = self.remove()
        self.assertEqual((result.returncode, result.stdout),
                         (0, f"lab-alma is not in {self.inventory}; nothing changed.\n"))
        self.assertEqual((self.state(), self.backups(), self.leftovers()), (after, backups, []))

    def test_a_group_name_is_refused(self):
        for name in ("lab", "ubuntu", "enterprise_linux", "all", "ungrouped"):
            with self.subTest(name=name):
                result = self.remove(name)
                self.assertEqual(result.stdout, f"{name} is the name of an inventory group, not of a host; "
                                                "nothing changed.\n")
                self.assertUnchanged(result, 1)

    def test_a_group_only_named_under_children_is_refused(self):
        inventory = INVENTORY.replace("[lab:children]\n", "[lab:children]\nlab-alma\n")
        self.inventory.write_text(inventory)
        result = self.remove()
        self.assertIn("is the name of an inventory group", result.stdout)
        self.assertUnchanged(result, 1, (inventory, self.state()[1]))

    def test_names_that_are_not_plain_tokens_are_refused(self):
        for name in ("lab-alma ansible_host=x", "-lab", ".*", "lab/alma", "labаlma"):
            with self.subTest(name=name):
                result = self.remove(name)
                self.assertEqual(result.stdout, "Inventory name must be a plain hostname-like token.\n")
                self.assertUnchanged(result, 1)

    def test_a_name_that_only_looks_alike_is_not_removed(self):
        # A dot is not a wildcard, and a name that is a prefix of another is a different name.
        for name in ("lab.alma", "lab-alm", "lab-alma2"):
            with self.subTest(name=name):
                result = self.remove(name)
                self.assertEqual(result.stdout, f"{name} is not in {self.inventory}; nothing changed.\n")
                self.assertUnchanged(result, 0)

    def test_a_line_with_other_settings_or_listed_twice_is_left_for_editing_by_hand(self):
        for line, message in ((f"lab-alma ansible_host={ALMA} ansible_port=2222", "with other settings"),
                              ("lab-alma", "with other settings"),
                              (f"lab-alma ansible_host={ALMA}\nlab-alma ansible_host={ALMA}", "on 2 lines")):
            with self.subTest(line=line):
                inventory = INVENTORY.replace(f"lab-alma ansible_host={ALMA}", line)
                self.inventory.write_text(inventory)
                result = self.remove()
                self.assertIn(message, result.stdout)
                self.assertIn("by hand", result.stdout)
                self.assertUnchanged(result, 1, (inventory, self.state()[1]))

    def test_a_host_that_shares_the_address_keeps_the_key(self):
        inventory = INVENTORY.replace("[ubuntu]\n", f"[ubuntu]\nlab-alma-old ansible_host={ALMA}\n")
        self.inventory.write_text(inventory)
        keys = self.state()[1]
        result = self.remove()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.state(), (inventory.replace(f"lab-alma ansible_host={ALMA}\n", ""), keys))
        self.assertIn(f"Kept the trusted host key of {ALMA} in {self.known_hosts}: lab-alma-old in the inventory "
                      "uses that address too.\n", result.stdout)

    def test_a_host_named_by_the_address_shares_it_too(self):
        inventory = INVENTORY.replace("[ubuntu]\n", f"[ubuntu]\n{ALMA}\n")
        self.inventory.write_text(inventory)
        keys = self.state()[1]
        self.assertEqual(self.remove().returncode, 0)
        self.assertEqual(self.state()[1], keys)

    def test_keep_key_leaves_known_hosts_alone(self):
        keys = self.state()[1]
        before = os.stat(self.known_hosts).st_ino
        result = self.remove("lab-alma", "--keep-key")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.state(), (WITHOUT_ALMA, keys))
        self.assertEqual(os.stat(self.known_hosts).st_ino, before)
        self.assertIn(f"Kept the trusted host key of {ALMA} in {self.known_hosts}, as --keep-key asks.\n",
                      result.stdout)

    def test_every_key_line_for_the_address_goes_hashed_ones_too(self):
        hashed = self.work / "hashed"
        hashed.write_text(f"{ALMA} {self.ubuntu_key['line']}\n")
        subprocess.run(["ssh-keygen", "-H", "-f", str(hashed)], check=True, capture_output=True)
        self.known_hosts.write_text(self.known_hosts.read_text() + hashed.read_text() + "# a comment\n")
        result = self.remove()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.state()[1], f"{UBUNTU} {self.ubuntu_key['line']}\n# a comment\n")
        self.assertIn(f"Removed 2 trusted host key line(s) for {ALMA}", result.stdout)
        self.assertIn(f"  {self.alma_key['fingerprint']} (RSA)\n  {self.ubuntu_key['fingerprint']} (RSA)\n",
                      result.stdout)

    def test_no_key_for_the_address_is_said(self):
        keys = f"{UBUNTU} {self.ubuntu_key['line']}\n"
        self.known_hosts.write_text(keys)
        result = self.remove()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.state(), (WITHOUT_ALMA, keys))
        self.assertIn(f"{self.known_hosts} held no key for {ALMA}.\n", result.stdout)

    def test_lines_naming_other_hosts_too_are_never_edited(self):
        prefix = TEST_NET.rsplit(".", 1)[0]
        for entry in (f"lab-alma,{ALMA}", f"@revoked {ALMA}", f"{prefix}.*.12", f"[{ALMA}]:22,{ALMA}"):
            with self.subTest(entry=entry):
                keys = f"{UBUNTU} {self.ubuntu_key['line']}\n{entry} {self.alma_key['line']}\n"
                self.known_hosts.write_text(keys)
                result = self.remove()
                self.assertIn(f"Line 2 of {self.known_hosts} names {ALMA} among other hosts", result.stdout)
                self.assertIn("--keep-key", result.stdout)
                self.assertUnchanged(result, 1, (INVENTORY, keys))

    def test_without_root_nothing_is_read_or_changed(self):
        result = self.remove(FAKE_UID="1000")
        self.assertEqual(result.stdout, "Run with sudo: the service known-hosts file is root-owned.\n")
        self.assertUnchanged(result, 1)

    def test_missing_files_and_links_are_refused(self):
        result = subprocess.run(["bash", str(SCRIPT), "--name", "lab-alma", "--lab-dir", str(self.work / "none"),
                                 "--known-hosts", str(self.known_hosts)],
                                capture_output=True, text=True, env=self.environment(), timeout=60)
        self.assertEqual((result.returncode, result.stdout), (1, "Missing inventory or known-hosts file.\n"))
        real = self.etc / "real_known_hosts"
        self.known_hosts.rename(real)
        self.known_hosts.symlink_to(real)
        result = self.remove()
        self.assertEqual((result.returncode, result.stdout),
                         (1, f"{self.known_hosts} is a symbolic link; edit it by hand instead.\n"))
        self.assertEqual(self.inventory.read_text(), INVENTORY)
        self.assertEqual(self.backups(), [])

    def test_usage_errors_exit_with_2(self):
        for arguments in ([], ["--name"], ["--name", "lab-alma", "--bogus"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(["bash", str(SCRIPT), *arguments], capture_output=True, text=True,
                                        env=self.environment(), timeout=60)
                self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(self.state()[0], INVENTORY)

    def test_a_failed_replacement_of_the_inventory_puts_known_hosts_back(self):
        # known-hosts is replaced first; then the inventory's replacement fails.
        real_mv = shutil.which("mv")
        self.stub("mv", f'for last; do :; done\ncase "$last" in */lab.ini) exit 1 ;; esac\nexec {real_mv} "$@"')
        before = os.stat(self.known_hosts)
        result = self.remove()
        self.assertEqual(result.stdout, f"Could not replace {self.inventory}.\n"
                                        f"Put {self.known_hosts} back as it was; nothing changed.\n")
        self.assertUnchanged(result, 1)
        after = os.stat(self.known_hosts)
        self.assertEqual((after.st_ino, stat.S_IMODE(after.st_mode)), (before.st_ino, 0o640))

    def test_a_failure_before_any_replacement_changes_nothing(self):
        for tool in ("chown", "cp", "ln"):
            with self.subTest(tool=tool):
                self.stub(tool, "exit 1")
                result = self.remove()
                self.assertIn("nothing changed", result.stdout)
                self.assertUnchanged(result, 1)
                (self.bin / tool).unlink()

    def test_runs_on_one_lab_folder_take_turns(self):
        # Each run reads both files, waits in ssh-keygen and replaces them. Without turns the
        # later replacement would bring back what the earlier one removed.
        environment = self.environment(KEYGEN_DELAY="1")
        runs = [subprocess.Popen(self.command(name), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 env=environment) for name in ("lab-alma", "lab-ubuntu")]
        for run in runs:
            stdout, stderr = run.communicate(timeout=60)
            self.assertEqual(run.returncode, 0, stdout + stderr)
        self.assertEqual(self.state(), (WITHOUT_ALMA.replace(f"lab-ubuntu ansible_host={UBUNTU}\n", ""), ""))
        self.assertEqual(len(self.backups()), 2)
        self.assertEqual(self.leftovers(), [])

    def test_a_run_that_does_not_get_its_turn_changes_nothing(self):
        self.stub("flock", "exit 1")
        result = self.remove()
        self.assertEqual(result.stdout, f"Another add-target.sh or remove-target.sh run is changing {self.lab}; "
                                        "run this again when it has finished.\n")
        self.assertUnchanged(result, 1)

    def test_it_undoes_what_add_target_did(self):
        # add-target.sh adds the line and the scanned key; remove-target.sh takes both away again.
        self.inventory.write_text(WITHOUT_ALMA)
        self.known_hosts.write_text(f"{UBUNTU} {self.ubuntu_key['line']}\n")
        scan = self.work / "scan.pub"
        scan.write_text(self.alma_key["line"])
        self.stub("ssh-keyscan", 'for last; do :; done\nprintf "%s %s\\n" "$last" "$(cat "$SCAN_KEY")"')
        added = subprocess.run(
            ["bash", str(ROOT / "controller" / "add-target.sh"), "--name", "lab-alma", "--address", ALMA,
             "--group", "enterprise_linux", "--fingerprint", self.alma_key["fingerprint"],
             "--lab-dir", str(self.lab), "--known-hosts", str(self.known_hosts)],
            capture_output=True, text=True, env=self.environment(SCAN_KEY=str(scan)), timeout=60)
        self.assertEqual(added.returncode, 0, added.stdout + added.stderr)
        self.assertEqual(self.inventory.read_text(), INVENTORY)
        result = self.remove()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.state(), (WITHOUT_ALMA, f"{UBUNTU} {self.ubuntu_key['line']}\n"))


if __name__ == "__main__":
    unittest.main()
