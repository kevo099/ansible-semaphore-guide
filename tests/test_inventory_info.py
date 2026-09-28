"""Offline tests: generated updates touch temporary fixtures only; SSH scans are fake."""

import base64
import contextlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "examples" / "onboard"
TEST_NET = ".".join(("192", "0", "2"))
SOURCE = (
    (HERE / "inventory-info.sh")
    .read_text()
    .split("<<'PY_INFO'\n", 1)[1]
    .rsplit("\nPY_INFO", 1)[0]
)
API = {"__name__": "inventory_info_test"}
exec(compile(SOURCE, str(HERE / "inventory-info.sh"), "exec"), API)


def public_key(fill):

    def field(data):
        return struct.pack(">I", len(data)) + data

    # Synthetic public RSA components; there are no corresponding private keys.
    blob = (
        field(b"ssh-rsa")
        + field(b"\x01\x00\x01")
        + field(b"\x00\x80" + bytes([fill]) * 255)
    )
    return "ssh-rsa " + base64.b64encode(blob).decode()


PUB1, PUB2 = (public_key(1), public_key(3))


def fingerprint(key):
    result = subprocess.run(
        ["ssh-keygen", "-l", "-E", "sha256", "-f", "-"],
        input=key + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.split()[1]


FP1 = fingerprint(PUB1)


class ControllerTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="inventory-info-test-")
        self.root = Path(self.temp.name)
        self.folder = self.root / "lab"
        self.inventory = self.folder / "inventories/lab.ini"
        self.inventory.parent.mkdir(parents=True)
        self.inventory.write_text(
            f"[ubuntu]\nold-ubuntu ansible_host={TEST_NET}.9\n\n[enterprise_linux]\n\n[lab:children]\nubuntu\nenterprise_linux\n\n[lab:vars]\nansible_user=svc_ansible\nansible_python_interpreter=/usr/bin/python3\n"
        )
        self.inventory.chmod(0o640)
        self.trust = self.root / "known_hosts"
        self.trust.write_text(
            f"# Existing unrelated trust\n{TEST_NET}.9 " + PUB2 + "\n"
        )
        self.trust.chmod(0o640)
        self.scan = self.root / "scanned-key"
        self.scan.write_text(f"{TEST_NET}.10 " + PUB1 + "\n")
        binary = self.root / "bin"
        binary.mkdir()
        scanner = binary / "ssh-keyscan"
        scanner.write_text('#!/bin/sh\ncat "$TEST_SCAN_FILE"\n')
        scanner.chmod(0o700)
        self.env = dict(
            os.environ,
            PATH=str(binary) + os.pathsep + os.environ["PATH"],
            TEST_SCAN_FILE=str(self.scan),
        )
        self.before = {p: p.read_bytes() for p in (self.inventory, self.trust)}

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, group="ubuntu", name="new-ubuntu", address=f"{TEST_NET}.10"):
        command = API["build_command"](name, address, group, FP1, str(self.folder))
        code = command.split("\n", 1)[1].rsplit("ADD_ANSIBLE_TARGET", 1)[0]
        code = code.replace(
            'Path("/etc/semaphore/known_hosts")', "Path(" + repr(str(self.trust)) + ")"
        )
        return subprocess.run(
            [sys.executable, "-c", code], text=True, capture_output=True, env=self.env
        )

    def unchanged(self):
        for path, content in self.before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse(list(self.root.rglob("*.before-add-*")))

    def test_add_and_repeat_preserve_other_hosts_permissions_and_backups(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"old-ubuntu ansible_host={TEST_NET}.9", self.inventory.read_text()
        )
        self.assertIn(
            f"[ubuntu]\nnew-ubuntu ansible_host={TEST_NET}.10\n",
            self.inventory.read_text(),
        )
        self.assertIn(f"{TEST_NET}.10 " + PUB1, self.trust.read_text())
        backups = list(self.root.rglob("*.before-add-*"))
        self.assertEqual(len(backups), 2)
        for path in (self.inventory, self.trust):
            backup = next(
                (p for p in backups if p.name.startswith(path.name + ".before-add-"))
            )
            self.assertEqual(backup.read_bytes(), self.before[path])
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        repeated = self.execute()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("Already present", repeated.stdout)
        self.assertEqual(len(list(self.root.rglob("*.before-add-*"))), 2)
        self.assertEqual(self.inventory.read_text().count("new-ubuntu "), 1)

    def test_enterprise_group(self):
        result = self.execute(group="enterprise_linux", name="new-rhel")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[enterprise_linux]\nnew-rhel ", self.inventory.read_text())

    def test_wrong_scanned_key_does_not_modify_either_file(self):
        self.scan.write_text(f"{TEST_NET}.10 " + PUB2 + "\n")
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fingerprint", result.stderr)
        self.unchanged()

    def test_unreachable_host_does_not_modify_either_file(self):
        self.scan.write_text("")
        self.assertNotEqual(self.execute().returncode, 0)
        self.unchanged()

    def test_conflicting_existing_name(self):
        result = self.execute(name="old-ubuntu")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different settings", result.stderr)
        self.unchanged()

    def test_address_already_under_another_alias(self):
        result = self.execute(address=f"{TEST_NET}.9")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another inventory name", result.stderr)
        self.unchanged()

    def test_hostname_can_match_a_child_group_name(self):
        result = self.execute(name="ubuntu")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"[ubuntu]\nubuntu ansible_host={TEST_NET}.10\n", self.inventory.read_text()
        )

    def test_quoted_address_is_not_duplicated(self):
        self.inventory.write_text(
            self.inventory.read_text().replace(
                f"ansible_host={TEST_NET}.9", f'ansible_host="{TEST_NET}.10"'
            )
        )
        self.before[self.inventory] = self.inventory.read_bytes()
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another inventory name", result.stderr)
        self.unchanged()

    def test_existing_rsa_conflict(self):
        self.trust.write_text(f"{TEST_NET}.10 " + PUB2 + "\n")
        self.before[self.trust] = self.trust.read_bytes()
        self.assertNotEqual(self.execute().returncode, 0)
        self.unchanged()

    def test_hashed_existing_trust_is_recognized(self):
        self.trust.write_text(f"{TEST_NET}.10 " + PUB1 + "\n")
        subprocess.run(
            ["ssh-keygen", "-q", "-H", "-f", str(self.trust)],
            capture_output=True,
            check=True,
        )
        before = self.trust.read_bytes()
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trust.read_bytes(), before)

    def test_missing_group_refuses(self):
        self.inventory.write_text(
            self.inventory.read_text().replace("[ubuntu]", "[different]")
        )
        self.before[self.inventory] = self.inventory.read_bytes()
        self.assertNotEqual(self.execute().returncode, 0)
        self.unchanged()

    def test_symlink_refuses(self):
        saved = self.inventory.with_suffix(".saved")
        self.inventory.rename(saved)
        self.inventory.symlink_to(saved)
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("regular file", result.stderr)
        self.unchanged()


class CollectorTests(unittest.TestCase):

    def test_group_mapping(self):
        for distro in ("rhel", "almalinux", "rocky"):
            self.assertEqual(
                API["group_for"]({"ID": distro, "VERSION_ID": "9.8"}),
                "enterprise_linux",
            )
        self.assertEqual(
            API["group_for"]({"ID": "ubuntu", "VERSION_ID": "24.04"}), "ubuntu"
        )
        with self.assertRaises(ValueError):
            API["group_for"]({"ID": "ubuntu", "VERSION_ID": "26.04"})

    def test_route_source_address_and_explicit_selection(self):
        interfaces = [
            {
                "addr_info": [
                    {"family": "inet", "scope": "global", "local": s}
                    for s in (f"{TEST_NET}.10", f"{TEST_NET}.200")
                ]
            }
        ]
        choose = API["choose_address"]
        self.assertEqual(
            choose(f"{TEST_NET}.5", "", interfaces, [{"prefsrc": f"{TEST_NET}.10"}]),
            f"{TEST_NET}.10",
        )
        self.assertEqual(choose("", f"{TEST_NET}.10", interfaces, []), f"{TEST_NET}.10")
        for controller, explicit, routes in [
            ("", "", []),
            (f"{TEST_NET}.10", f"{TEST_NET}.10", []),
            (f"{TEST_NET}.5", f"{TEST_NET}.20", []),
            (f"{TEST_NET}.5", "", []),
        ]:
            with self.assertRaises(ValueError):
                choose(controller, explicit, interfaces, routes)

    def test_generated_values_cannot_inject_shell_or_python(self):
        for name in ("$(id)", "a;id", "a\nADD_ANSIBLE_TARGET", "-option"):
            with self.assertRaises(ValueError):
                API["build_command"](
                    name, f"{TEST_NET}.10", "ubuntu", FP1, "/opt/ansible-lab"
                )
        command = API["build_command"](
            "host", f"{TEST_NET}.10", "ubuntu", FP1, "/opt/a'b"
        )
        compile(
            command.split("\n", 1)[1].rsplit("ADD_ANSIBLE_TARGET", 1)[0],
            "<generated>",
            "exec",
        )

    def test_full_output_fits_azure_and_reports_sudo_failure_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "os-release"
            release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            ssh = root / "targetuser/.ssh"
            ssh.mkdir(parents=True)
            (ssh / "authorized_keys").write_text(PUB1 + "\n")

            def fake_run(args):
                command = args[0]
                if command == "ip" and "address" in args:
                    out = json.dumps(
                        [
                            {
                                "addr_info": [
                                    {
                                        "family": "inet",
                                        "scope": "global",
                                        "local": f"{TEST_NET}.10",
                                    }
                                ]
                            }
                        ]
                    )
                elif command == "ip":
                    out = json.dumps([{"prefsrc": f"{TEST_NET}.10"}])
                elif command == "ssh-keygen":
                    out = "2048 " + FP1 + " root@fixture (RSA)\n"
                elif command == "passwd":
                    out = "svc_ansible P 09/28/2026 0 99999 7 -1\n"
                elif command == "/usr/sbin/visudo":
                    return subprocess.CompletedProcess(
                        args, 1, "", "PRIVATE_DIAGNOSTIC_NOT_FOR_OUTPUT"
                    )
                else:
                    raise AssertionError(args)
                return subprocess.CompletedProcess(args, 0, out, "")

            def fake_path(value):
                return release if str(value) == "/etc/os-release" else Path(value)

            with mock.patch.dict(
                API,
                {
                    "run": fake_run,
                    "Path": fake_path,
                    "pwd": SimpleNamespace(
                        getpwnam=lambda _: SimpleNamespace(
                            pw_dir=str(root / "targetuser")
                        )
                    ),
                    "socket": SimpleNamespace(
                        gethostname=lambda: "target-ubuntu.example.test"
                    ),
                },
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    API["main"]([f"{TEST_NET}.5", "", "", "/opt/ansible-lab"])
            text = output.getvalue()
            self.assertLessEqual(len(text.encode()), 3900)
            self.assertIn("sudo INVALID", text)
            self.assertIn("password set", text)
            self.assertNotIn("PRIVATE_DIAGNOSTIC", text)
            self.assertTrue(text.endswith("ADD_ANSIBLE_TARGET\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
