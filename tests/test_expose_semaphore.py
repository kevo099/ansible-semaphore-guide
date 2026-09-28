"""Exercise exposure transitions without packages, services, root or networking."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]

MOCK_COMMAND = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a") as stream:
    stream.write(json.dumps([name, *args]) + "\n")
if name == "id":
    print("0")
elif name == "install":
    # Preserve real directory creation and modes, with no root ownership changes.
    unprivileged = []
    remaining = iter(args)
    for argument in remaining:
        if argument in ("-o", "-g"):
            next(remaining)
        else:
            unprivileged.append(argument)
    sys.exit(subprocess.run(["/usr/bin/install", *unprivileged]).returncode)
elif name == "systemctl" and args[0] == "is-active":
    if args[-1] == "firewalld":
        sys.exit(0 if os.environ.get("MOCK_FIREWALL") == "firewalld" else 3)
elif name == "ufw" and args == ["status"]:
    print("Status: active")
elif name == "apt-get" and "update" in args:
    sys.exit(int(os.environ.get("MOCK_APT_UPDATE_STATUS", "0")))
elif name == "nginx" and args == ["-T"]:
    for path in Path(os.environ["MOCK_NGINX"]).glob("sites-enabled/*"):
        print(path.read_text())
elif name == "openssl":
    if args[0] == "req":
        Path(args[args.index("-keyout") + 1]).write_text("PRIVATE TEST KEY\n")
        Path(args[args.index("-out") + 1]).write_text("TEST CERTIFICATE\n")
    elif "-fingerprint" in args:
        print("sha256 Fingerprint=TEST:FINGERPRINT")
    else:
        print("Certificate does match hostname")
'''


class ExposureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.configuration = self.directory / "semaphore"
        self.configuration.mkdir()
        self.config_file = self.configuration / "config.json"
        self.config_file.write_text(json.dumps({"interface": "127.0.0.1", "port": ":3000"}))
        self.nginx = self.directory / "nginx"
        (self.nginx / "sites-enabled").mkdir(parents=True)
        (self.nginx / "conf.d").mkdir()
        (self.nginx / "nginx.conf").write_text("# Original package configuration\n")
        self.default_site = self.nginx / "sites-enabled" / "default"
        self.default_site.write_text("server {\n    listen 80;\n}\n")
        self.os_release = self.directory / "os-release"
        self.os_release.write_text("ID=ubuntu\nVERSION_ID=24.04\n")
        self.log = self.directory / "commands.jsonl"
        self.log.touch()
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        for name in ("id", "chown", "install", "systemctl", "ufw", "apt-get", "nginx",
                     "openssl", "curl", "dnf", "setsebool", "firewall-cmd"):
            executable = self.bin / name
            executable.write_text(textwrap.dedent(MOCK_COMMAND))
            executable.chmod(0o755)
        # Only the filesystem locations are relocated. The original script's
        # argument handling, distro branches, readiness checks and transitions run.
        script = (ROOT / "scripts" / "expose-semaphore.sh").read_text()
        for original, replacement in (("/etc/semaphore", self.configuration),
                                      ("/etc/nginx", self.nginx),
                                      ("/etc/os-release", self.os_release)):
            script = script.replace(original, str(replacement))
        self.script = self.directory / "expose-semaphore.sh"
        self.script.write_text(script)

    def run_mode(self, mode, **environment):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                   MOCK_LOG=str(self.log), MOCK_NGINX=str(self.nginx), **environment)
        return subprocess.run(["bash", str(self.script), "--mode", mode,
                               "--address", "controller.example.test"],
                              env=env, capture_output=True, text=True)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_ubuntu_https_uses_apt_ufw_and_loopback_proxy(self):
        result = self.run_mode("https")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.commands()
        self.assertIn(["apt-get", "-qq", "update"], commands)
        self.assertIn(["apt-get", "-qq", "install", "-y", "nginx", "openssl"], commands)
        self.assertIn(["ufw", "allow", "443/tcp"], commands)
        self.assertIn(["ufw", "delete", "allow", "3000/tcp"], commands)
        self.assertFalse(any(command[0] in ("dnf", "setsebool", "firewall-cmd") for command in commands))
        self.assertFalse(self.default_site.exists())
        site = (self.nginx / "sites-enabled" / "semaphore-tls.conf").read_text()
        self.assertIn("listen 443 ssl;", site)
        self.assertIn("proxy_pass http://127.0.0.1:3000;", site)
        self.assertEqual(json.loads(self.config_file.read_text())["interface"], "127.0.0.1")
        self.assertEqual((self.configuration / "exposure").read_text(), "https\n")
        self.assertNotIn("PRIVATE TEST KEY", result.stdout + result.stderr)

    def test_failed_ubuntu_package_update_stops_before_exposure_changes(self):
        result = self.run_mode("https", MOCK_APT_UPDATE_STATUS="100")
        self.assertEqual(result.returncode, 100, result.stdout + result.stderr)
        commands = self.commands()
        self.assertFalse(any(command[0] in ("systemctl", "ufw", "openssl") for command in commands))
        self.assertFalse(any(command[0] == "apt-get" and "install" in command for command in commands))
        self.assertTrue(self.default_site.exists())
        self.assertFalse((self.configuration / "exposure").exists())

    def test_https_http_loopback_transitions_close_previous_ufw_ports(self):
        for mode in ("https", "http", "loopback"):
            with self.subTest(mode=mode):
                self.log.write_text("")
                result = self.run_mode(mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                commands = self.commands()
                if mode == "http":
                    self.assertIn(["ufw", "delete", "allow", "443/tcp"], commands)
                    self.assertIn(["ufw", "allow", "3000/tcp"], commands)
                    self.assertIn(["systemctl", "disable", "--now", "nginx"], commands)
                    self.assertEqual(json.loads(self.config_file.read_text())["interface"], "0.0.0" + ".0")
                    self.assertFalse((self.nginx / "sites-enabled" / "semaphore-tls.conf").exists())
                elif mode == "loopback":
                    self.assertIn(["ufw", "delete", "allow", "443/tcp"], commands)
                    self.assertIn(["ufw", "delete", "allow", "3000/tcp"], commands)
                    self.assertEqual(json.loads(self.config_file.read_text())["interface"], "127.0.0.1")
                    self.assertFalse((self.configuration / "exposure").exists())

    def test_el9_exposure_keeps_dnf_selinux_and_firewalld(self):
        self.os_release.write_text("ID=almalinux\nVERSION_ID=9.7\n")
        result = self.run_mode("https", MOCK_FIREWALL="firewalld")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.commands()
        self.assertIn(["dnf", "-y", "-q", "install", "nginx", "openssl", "policycoreutils-python-utils"], commands)
        self.assertIn(["setsebool", "-P", "httpd_can_network_connect", "1"], commands)
        self.assertIn(["firewall-cmd", "-q", "--permanent", "--add-service=https"], commands)
        self.assertTrue((self.nginx / "conf.d" / "semaphore-tls.conf").exists())
        self.assertTrue((self.nginx / "nginx.conf.before-semaphore").exists())
        self.assertFalse(any(command[0] in ("apt-get", "ufw") for command in commands))


if __name__ == "__main__":
    unittest.main()
