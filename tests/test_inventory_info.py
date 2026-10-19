"""Offline tests of the Run Command collector: it prints data and one add-target.sh line, never code."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
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

# The SHA256: form ssh-keygen -l prints: 43 base64 characters, no padding.
FINGERPRINT = "SHA256:" + "A1b2C3d4" * 5 + "E5f"
UBUNTU = 'ID=ubuntu\nVERSION_ID="24.04"\n'
ALMALINUX = 'ID="almalinux"\nVERSION_ID="9.8"\n'
SET_PASSWORD = "svc_ansible:$6$salt$hash:20000:0:99999:7:::\n"


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

    def test_the_line_is_one_add_target_command(self):
        build = API["build_command"]
        self.assertEqual(
            build("lab-alma", f"{TEST_NET}.12", "enterprise_linux", FINGERPRINT, "/opt/ansible-lab"),
            f"sudo bash scripts/add-target.sh --name lab-alma --address {TEST_NET}.12"
            f" --group enterprise_linux --fingerprint {FINGERPRINT}",
        )
        # The folder is named only when add-target.sh would not find it by itself.
        self.assertTrue(
            build("lab-ubuntu", f"{TEST_NET}.10", "ubuntu", FINGERPRINT, "/srv/lab.d/ansible_lab-2")
            .endswith(f"--fingerprint {FINGERPRINT} --lab-dir /srv/lab.d/ansible_lab-2")
        )

    def test_values_that_are_not_plain_tokens_are_refused(self):
        build = API["build_command"]
        good = {"name": "host", "address": f"{TEST_NET}.10", "group": "ubuntu",
                "fingerprint": FINGERPRINT, "folder": "/opt/ansible-lab"}
        for field, value in [
            ("name", "$(id)"), ("name", "a;id"), ("name", "a\nb"), ("name", "-option"),
            ("name", "a b"), ("name", "x" * 64),
            ("address", "host.example.test"), ("address", f"{TEST_NET}.10;id"),
            ("group", "lab"),
            ("fingerprint", "SHA256:short"), ("fingerprint", FINGERPRINT + " x"),
            ("folder", "/opt/a'b"), ("folder", "/opt/a b"), ("folder", "opt/ansible-lab"),
            ("folder", "/opt/$(id)"), ("folder", "/opt/a\nb"), ("folder", "/" + "a" * 200),
        ]:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    build(**dict(good, **{field: value}))

    def collect(self, release=UBUNTU, shadow=SET_PASSWORD, visudo=0, name="", folder="/opt/ansible-lab"):
        """Run main() with simulated system commands; return its output and the commands it ran."""
        commands = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "os-release").write_text(release)
            ssh = root / "targetuser/.ssh"
            ssh.mkdir(parents=True)
            (ssh / "authorized_keys").write_text("ssh-rsa AAAAB3NzaC1yc2E fixture\n")

            def fake_run(args):
                commands.append(args[0])
                if args[0] == "ip" and "address" in args:
                    out = json.dumps([{"addr_info": [
                        {"family": "inet", "scope": "global", "local": f"{TEST_NET}.10"}]}])
                elif args[0] == "ip":
                    out = json.dumps([{"prefsrc": f"{TEST_NET}.10"}])
                elif args[0] == "ssh-keygen":
                    out = "3072 " + FINGERPRINT + " root@fixture (RSA)\n"
                elif args[0] == "getent":
                    return subprocess.CompletedProcess(args, 0 if shadow else 2, shadow, "")
                elif args[0] == "/usr/sbin/visudo":
                    return subprocess.CompletedProcess(args, visudo, "", "PRIVATE_DIAGNOSTIC_NOT_FOR_OUTPUT")
                else:
                    raise AssertionError(args)
                return subprocess.CompletedProcess(args, 0, out, "")

            def fake_path(value):
                return root / "os-release" if str(value) == "/etc/os-release" else Path(value)

            with mock.patch.dict(API, {
                "run": fake_run,
                "Path": fake_path,
                "pwd": SimpleNamespace(getpwnam=lambda _: SimpleNamespace(pw_dir=str(root / "targetuser"))),
                "socket": SimpleNamespace(gethostname=lambda: "target-ubuntu.example.test"),
            }):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    API["main"]([f"{TEST_NET}.5", "", name, folder])
        return output.getvalue(), commands

    def test_output_is_data_ending_with_the_add_target_line(self):
        text, _ = self.collect()
        lines = text.splitlines()
        self.assertEqual(lines[0], f"VM: target-ubuntu | {TEST_NET}.10 | ubuntu 24.04")
        self.assertEqual(lines[1], "RSA: " + FINGERPRINT)
        self.assertEqual(lines[2], "SSH keys present; password set; sudo syntax OK")
        self.assertEqual(lines[-2], "Add it on the controller, in the guide checkout:")
        self.assertEqual(
            lines[-1],
            f"  sudo bash scripts/add-target.sh --name target-ubuntu --address {TEST_NET}.10"
            f" --group ubuntu --fingerprint {FINGERPRINT}",
        )
        self.assertTrue(text.endswith("\n"))
        # Nothing for the controller to run but that one line of reviewed code.
        for code in ("python3", "<<", "ADD_ANSIBLE_TARGET", "$(", "`"):
            self.assertNotIn(code, text)

    def test_full_output_fits_azure_and_reports_sudo_failure_without_secrets(self):
        text, _ = self.collect(visudo=1, name="n" * 63, folder="/" + "f" * 199)
        self.assertLessEqual(len(text.encode()), 3900)
        self.assertIn("sudo INVALID", text)
        self.assertNotIn("PRIVATE_DIAGNOSTIC", text)
        self.assertTrue(text.endswith(" --lab-dir /" + "f" * 199 + "\n"))

    def test_enterprise_linux_password_is_read_from_the_shadow_entry(self):
        text, commands = self.collect(release=ALMALINUX)
        self.assertIn("SSH keys present; password set; sudo syntax OK", text)
        self.assertIn("--group enterprise_linux", text)
        self.assertNotIn("passwd", commands)
        for shadow in ("svc_ansible:!$6$salt$hash:20000:0:99999:7:::\n", "svc_ansible:!!:20000::::::\n",
                       "svc_ansible:*:20000::::::\n", ""):
            with self.subTest(shadow=shadow):
                text, _ = self.collect(release=ALMALINUX, shadow=shadow)
                self.assertIn("WARNING: password unset/locked/unverified", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
