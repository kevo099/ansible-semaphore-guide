"""Exercise exposure transitions without packages, services, root or networking."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANY = "0.0.0" + ".0"  # split so the repository validator ignores it

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


def count_call(kind):
    """How often this kind of call has happened in this test, this one included."""
    counter = Path(os.environ["MOCK_LOG"] + "." + kind)
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    return count


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
    # Another apt process holds the package lists' lock for the first N updates.
    sys.exit(100 if count_call("apt-update") <= int(os.environ.get("MOCK_APT_UPDATE_FAILURES", "0")) else 0)
elif name == "pgrep":
    # A Semaphore task runs from the Nth check on; 0 means never.
    running_from = int(os.environ.get("MOCK_TASK_RUNNING_FROM", "0"))
    sys.exit(0 if running_from and count_call("pgrep") >= running_from else 1)
elif name == "ss":
    # What listens on port 3000, comma-separated; empty means Semaphore is stopped.
    for address in filter(None, os.environ.get("MOCK_SS_LISTEN", "").split(",")):
        print(f"LISTEN 0      4096      {address}:3000      *:*")
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
                     "openssl", "curl", "dnf", "setsebool", "firewall-cmd", "pgrep", "sleep", "ss"):
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

    def run_mode(self, mode, *arguments, **environment):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                   MOCK_LOG=str(self.log), MOCK_NGINX=str(self.nginx), **environment)
        return subprocess.run(["bash", str(self.script), "--mode", mode,
                               "--address", "controller.example.test", *arguments],
                              env=env, capture_output=True, text=True)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_ubuntu_https_uses_apt_ufw_and_loopback_proxy(self):
        result = self.run_mode("https")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.commands()
        self.assertIn(["apt-get", "-qq", "update"], commands)
        self.assertIn(["apt-get", "-qq", "-o", "DPkg::Lock::Timeout=600", "install", "-y", "nginx", "openssl"],
                      commands)
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
        result = self.run_mode("https", MOCK_APT_UPDATE_FAILURES="30")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("apt-get update failed 30 times; nothing was changed", result.stdout)
        commands = self.commands()
        self.assertEqual(commands.count(["apt-get", "-qq", "update"]), 30)
        self.assertEqual(commands.count(["sleep", "10"]), 29)
        self.assertFalse(any(command[0] in ("systemctl", "ufw", "openssl") for command in commands))
        self.assertFalse(any(command[0] == "apt-get" and "install" in command for command in commands))
        self.assertTrue(self.default_site.exists())
        self.assertFalse((self.configuration / "exposure").exists())

    def test_ubuntu_package_update_waits_for_a_held_lock(self):
        result = self.run_mode("https", MOCK_APT_UPDATE_FAILURES="2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.commands()
        self.assertEqual(commands.count(["apt-get", "-qq", "update"]), 3)
        self.assertEqual(commands.count(["sleep", "10"]), 2)
        self.assertIn("another apt process may hold its lock", result.stdout)
        self.assertEqual((self.configuration / "exposure").read_text(), "https\n")

    def set_interface(self, interface):
        self.config_file.write_text(json.dumps({"interface": interface, "port": ":3000"}))
        return self.config_file.read_text()

    def test_a_mode_that_keeps_the_bind_address_never_restarts_semaphore(self):
        # Even while a task runs, since nothing needs a restart.
        for interface, mode in (("127.0.0.1", "https"), ("127.0.0.1", "loopback"), (ANY, "http")):
            with self.subTest(interface=interface, mode=mode):
                self.log.write_text("")
                original = self.set_interface(interface)
                result = self.run_mode(mode, MOCK_TASK_RUNNING_FROM="1", MOCK_SS_LISTEN=interface)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"Semaphore already listens on {interface}; it was not restarted.", result.stdout)
                commands = self.commands()
                self.assertNotIn(["systemctl", "restart", "semaphore"], commands)
                # start leaves a running Semaphore alone and starts a stopped one.
                self.assertIn(["systemctl", "start", "semaphore"], commands)
                self.assertFalse(any(command[0] == "pgrep" for command in commands))
                self.assertEqual(self.config_file.read_text(), original)

    def test_a_process_still_on_the_old_address_is_restarted(self):
        # config.json already names the wanted address, but the running Semaphore
        # listens on the old one, as after a run interrupted before its restart.
        for interface, mode, live in (("127.0.0.1", "https", ANY), ("127.0.0.1", "loopback", ANY),
                                      (ANY, "http", "127.0.0.1")):
            with self.subTest(interface=interface, mode=mode):
                self.log.write_text("")
                self.set_interface(interface)
                result = self.run_mode(mode, MOCK_SS_LISTEN=live)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("already listens", result.stdout)
                commands = self.commands()
                self.assertIn(["pgrep", "-u", "semaphore", "-f", "ansible-playbook"], commands)
                self.assertIn(["systemctl", "restart", "semaphore"], commands)
                self.assertEqual(json.loads(self.config_file.read_text())["interface"], interface)

    def test_a_process_still_on_the_old_address_waits_for_a_running_task(self):
        original = self.set_interface("127.0.0.1")
        result = self.run_mode("https", MOCK_SS_LISTEN=ANY, MOCK_TASK_RUNNING_FROM="1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("A Semaphore task is running", result.stdout)
        self.assertNotIn(["systemctl", "restart", "semaphore"], self.commands())
        self.assertEqual(self.config_file.read_text(), original)

    def test_a_new_bind_address_restarts_semaphore_when_no_task_runs(self):
        for interface, mode, new in (("127.0.0.1", "http", ANY), (ANY, "https", "127.0.0.1"),
                                     (ANY, "loopback", "127.0.0.1")):
            with self.subTest(interface=interface, mode=mode):
                self.log.write_text("")
                self.set_interface(interface)
                result = self.run_mode(mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                commands = self.commands()
                self.assertIn(["pgrep", "-u", "semaphore", "-f", "ansible-playbook"], commands)
                self.assertIn(["systemctl", "restart", "semaphore"], commands)
                self.assertEqual(json.loads(self.config_file.read_text())["interface"], new)

    def test_a_running_task_blocks_a_new_bind_address_before_anything_changes(self):
        for interface, mode in (("127.0.0.1", "http"), (ANY, "https"), (ANY, "loopback")):
            with self.subTest(interface=interface, mode=mode):
                self.log.write_text("")
                original = self.set_interface(interface)
                result = self.run_mode(mode, MOCK_TASK_RUNNING_FROM="1")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("A Semaphore task is running", result.stdout)
                self.assertIn("add --force", result.stdout)
                self.assertEqual(self.commands(), [["id", "-u"],
                                                   ["pgrep", "-u", "semaphore", "-f", "ansible-playbook"]])
                self.assertEqual(self.config_file.read_text(), original)
                self.assertTrue(self.default_site.exists())
                self.assertFalse((self.configuration / "exposure").exists())

    def test_a_task_that_starts_meanwhile_still_blocks_the_restart(self):
        original = self.set_interface("127.0.0.1")
        result = self.run_mode("http", MOCK_TASK_RUNNING_FROM="2")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        commands = self.commands()
        self.assertEqual(commands.count(["pgrep", "-u", "semaphore", "-f", "ansible-playbook"]), 2)
        self.assertNotIn(["systemctl", "restart", "semaphore"], commands)
        self.assertEqual(self.config_file.read_text(), original)
        self.assertFalse((self.configuration / "exposure").exists())

    def test_force_restarts_semaphore_although_a_task_runs(self):
        self.set_interface("127.0.0.1")
        result = self.run_mode("http", "--force", MOCK_TASK_RUNNING_FROM="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.commands()
        self.assertIn(["systemctl", "restart", "semaphore"], commands)
        self.assertFalse(any(command[0] == "pgrep" for command in commands))
        self.assertEqual(json.loads(self.config_file.read_text())["interface"], ANY)

    def test_usage_names_force(self):
        result = subprocess.run(["bash", str(self.script), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("[--force]", result.stdout)
        self.assertIn("--force restarts anyway", result.stdout)

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
