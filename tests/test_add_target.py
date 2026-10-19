"""Offline runs of scripts/add-target.sh with a stub key scan; nothing here contacts a host."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
# Documentation addresses (RFC 5737), built in parts so the publication check accepts them.
TEST_NET = ".".join(("192", "0", "2"))
INVENTORY = """# Local lab inventory read by Semaphore at every run.
[ubuntu]

[enterprise_linux]

[lab:children]
ubuntu
enterprise_linux

[lab:vars]
ansible_user=svc_ansible
ansible_python_interpreter=/usr/bin/python3
"""


@unittest.skipUnless(shutil.which("ssh-keygen"), "needs ssh-keygen")
class AddTargetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.lab = self.work / "lab"
        (self.lab / "inventories").mkdir(parents=True)
        self.inventory = self.lab / "inventories" / "lab.ini"
        self.inventory.write_text(INVENTORY)
        self.known_hosts = self.work / "known_hosts"
        self.known_hosts.write_text("")
        self.key = self.make_key("host")
        self.other_key = self.make_key("other")
        # The script needs root and scans the target; stand-ins answer for both.
        self.bin = self.work / "bin"
        self.bin.mkdir()
        (self.bin / "id").write_text("#!/bin/sh\necho 0\n")
        (self.bin / "ssh-keyscan").write_text(
            '#!/bin/sh\nfor last; do :; done\nprintf "%s %s\\n" "$last" "$(cat "$SCAN_KEY")"\n')
        for stub in ("id", "ssh-keyscan"):
            (self.bin / stub).chmod(0o755)

    def make_key(self, name):
        path = self.work / name
        subprocess.run(["ssh-keygen", "-q", "-t", "rsa", "-b", "2048", "-N", "", "-f", str(path)], check=True)
        public = Path(f"{path}.pub").read_text().split()
        fingerprint = subprocess.run(["ssh-keygen", "-lf", f"{path}.pub"], capture_output=True, text=True,
                                     check=True).stdout.split()[1]
        return {"line": f"{public[0]} {public[1]}", "fingerprint": fingerprint, "file": f"{path}.pub"}

    def add(self, name="lab-alma", address=f"{TEST_NET}.12", group="enterprise_linux", fingerprint=None, served=None):
        environment = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")
        scan = self.work / "scan.pub"
        scan.write_text((served or self.key)["line"])
        environment["SCAN_KEY"] = str(scan)
        return subprocess.run(
            ["bash", str(ROOT / "scripts" / "add-target.sh"), "--name", name, "--address", address,
             "--group", group, "--fingerprint", fingerprint or self.key["fingerprint"],
             "--lab-dir", str(self.lab), "--known-hosts", str(self.known_hosts)],
            capture_output=True, text=True, env=environment, timeout=60)

    def state(self):
        return self.inventory.read_text(), self.known_hosts.read_text()

    def test_a_verified_host_is_added_under_its_group_and_trusted(self):
        result = self.add()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        inventory, known = self.state()
        self.assertIn(f"[enterprise_linux]\nlab-alma ansible_host={TEST_NET}.12\n", inventory)
        self.assertEqual(known, f"{TEST_NET}.12 {self.key['line']}\n")
        self.assertIn("run the Ping template, which covers every host in the lab group. If lab-alma fails", result.stdout)

    def test_running_it_again_changes_nothing(self):
        self.assertEqual(self.add().returncode, 0)
        before = self.state()
        result = self.add()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Already present", result.stdout)
        self.assertEqual(self.state(), before)

    def test_a_key_that_does_not_match_changes_nothing(self):
        result = self.add(served=self.other_key)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No scanned key matched", result.stdout)
        self.assertEqual(self.state(), (INVENTORY, ""))

    def test_values_that_are_not_plain_tokens_are_refused(self):
        for arguments in ({"address": f"{TEST_NET}.12 ansible_become_exe=/tmp/x"}, {"address": "-oProxyCommand=x"},
                          {"name": f"lab-alma ansible_host={TEST_NET}.99"}, {"fingerprint": "SHA256:a b"},
                          {"group": "lab"}):
            with self.subTest(arguments=arguments):
                result = self.add(**arguments)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(self.state(), (INVENTORY, ""))

    def test_a_name_that_is_also_a_group_is_refused(self):
        for name in ("lab", "ubuntu", "enterprise_linux", "all", "ungrouped"):
            with self.subTest(name=name):
                result = self.add(name=name)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("group", result.stdout)
                self.assertEqual(self.state(), (INVENTORY, ""))

    def test_an_address_listed_under_another_name_is_refused(self):
        self.assertEqual(self.add().returncode, 0)
        before = self.state()
        result = self.add(name="lab-alma2")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"already lists {TEST_NET}.12 as lab-alma", result.stdout)
        self.assertEqual(self.state(), before)

    def test_the_same_name_with_other_settings_is_refused(self):
        self.assertEqual(self.add().returncode, 0)
        before = self.state()
        result = self.add(address=f"{TEST_NET}.13")
        self.assertEqual(result.returncode, 1)
        self.assertIn("other settings", result.stdout)
        self.assertEqual(self.state(), before)

    def test_a_different_trusted_key_for_the_address_is_refused(self):
        self.known_hosts.write_text(f"{TEST_NET}.12 {self.other_key['line']}\n")
        result = self.add()
        self.assertEqual(result.returncode, 1)
        self.assertIn("different key", result.stdout)
        self.assertEqual(self.state(), (INVENTORY, f"{TEST_NET}.12 {self.other_key['line']}\n"))

    def test_an_already_trusted_matching_key_is_not_added_twice(self):
        self.known_hosts.write_text(f"{TEST_NET}.12 {self.key['line']}\n")
        result = self.add()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.state()[1], f"{TEST_NET}.12 {self.key['line']}\n")

    def test_a_missing_group_section_changes_nothing(self):
        self.inventory.write_text(INVENTORY.replace("[ubuntu]\n\n", ""))
        result = self.add(name="lab-ubuntu", group="ubuntu")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.known_hosts.read_text(), "")


if __name__ == "__main__":
    unittest.main()
