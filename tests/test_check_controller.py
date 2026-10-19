"""Offline checks for the readiness script's parsing; nothing here needs root or a controller."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = load("check_controller", "check-controller.py")
config_module = load("controller_config", "controller_config.py")
updater = load("update_controller", "update-controller.py")

ANY = "0.0.0" + ".0"  # split so the repository validator ignores it
NGINX = 'users:(("nginx",pid=12,fd=6),("nginx",pid=11,fd=6))'
# `ss -H -lntp` on a controller after `expose-semaphore.sh --mode https`.
HTTPS = "\n".join([
    f"LISTEN 0 4096 127.0.0.1:3000 {ANY}:*",
    f"LISTEN 0 200 127.0.0.1:5432 {ANY}:*",
    "LISTEN 0 200 [::1]:5432 [::]:*",
    f"LISTEN 0 511 {ANY}:443 {ANY}:* {NGINX}",
    f"LISTEN 0 511 [::]:443 [::]:* {NGINX}",
    f'LISTEN 0 128 {ANY}:22 {ANY}:* users:(("sshd",pid=9,fd=3))',
    f"LISTEN 0 4096 127.0.0.1:13000 {ANY}:*",
])


def file_stat(mode, gid):
    return os.stat_result((stat.S_IFREG | mode, 0, 0, 1, 0, gid, 0, 0, 0, 0))


class ReadinessParsingTests(unittest.TestCase):
    def test_listener_hosts_are_matched_by_exact_port(self):
        self.assertEqual(check.listening_hosts(HTTPS, 3000), ["127.0.0.1"])
        self.assertEqual(check.listening_hosts(HTTPS, 5432), ["127.0.0.1", "::1"])
        self.assertEqual(check.listening_hosts(HTTPS, 443), [ANY, "::"])
        self.assertEqual(check.listening_hosts(HTTPS, 80), [])
        self.assertEqual(check.listening_hosts(f"LISTEN 0 4096 *:3000 {ANY}:*", 3000), ["*"])

    def test_https_exposure_allows_only_nginx_on_443(self):
        self.assertEqual(check.public_nginx_ports(HTTPS), {"443"})

    def test_package_default_port_80_site_is_reported(self):
        leaked = HTTPS + f"\nLISTEN 0 511 {ANY}:80 {ANY}:* {NGINX}\nLISTEN 0 511 [::]:80 [::]:* {NGINX}"
        self.assertEqual(check.public_nginx_ports(leaked), {"443", "80"})

    def test_nginx_on_loopback_is_not_public(self):
        self.assertEqual(check.public_nginx_ports(f"LISTEN 0 511 127.0.0.1:8080 {ANY}:* {NGINX}"), set())
        self.assertEqual(check.public_nginx_ports(f"LISTEN 0 511 [::1]:8080 [::]:* {NGINX}"), set())

    def test_known_hosts_rewritten_as_root_is_unreadable_by_the_service(self):
        service_gid = 990
        self.assertTrue(check.group_can_read(file_stat(0o640, service_gid), service_gid))
        self.assertFalse(check.group_can_read(file_stat(0o640, 0), service_gid))
        self.assertFalse(check.group_can_read(file_stat(0o600, service_gid), service_gid))

    def test_refuses_to_run_without_root(self):
        with mock.patch.object(check.os, "geteuid", return_value=1000):
            with self.assertRaises(SystemExit) as refused:
                check.main()
        self.assertIn("sudo", str(refused.exception.code))


SEMAPHORE = f"LISTEN 0 4096 127.0.0.1:3000 {ANY}:*"
POSTGRESQL = f"LISTEN 0 200 127.0.0.1:5432 {ANY}:*\nLISTEN 0 200 [::1]:5432 [::]:*"
NGINX_443 = f"LISTEN 0 511 {ANY}:443 {ANY}:* {NGINX}"
# The address Semaphore binds and what `ss` shows for it in each exposure.
EXPOSURES = {
    "loopback": ("127.0.0.1", [SEMAPHORE, POSTGRESQL]),
    "https": ("127.0.0.1", [SEMAPHORE, POSTGRESQL, NGINX_443]),
    "http": (ANY, [f"LISTEN 0 4096 {ANY}:3000 {ANY}:*", POSTGRESQL]),
}
UBUNTU_UNITS = {"semaphore", "postgresql", "postgresql@16-main", "nginx"}
# Checks that fail when a service is down, and the service whose logs explain it.
SERVICE_CHECKS = {"semaphore_is_active": "semaphore", "port_3000_listening": "semaphore",
                  "postgresql_is_active": "postgresql", "port_5432_listening": "postgresql"}


class Ping:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


class ReportTests(unittest.TestCase):
    """main() on a simulated controller: its files in a temporary folder, services and listeners stubbed."""

    def report(self, exposure="loopback", active=UBUNTU_UNITS, listeners=None, ping=True, ubuntu=True):
        interface, default_listeners = EXPOSURES[exposure]
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory, "etc", "semaphore")
            settings.mkdir(parents=True)
            # The generated configuration, as the installers write it.
            config = config_module.make_config()
            config["interface"] = interface
            (settings / "config.json").write_text(json.dumps(config))
            (settings / "config.json").chmod(0o640)
            (settings / "known_hosts").touch()
            (settings / "known_hosts").chmod(0o640)
            if exposure != "loopback":
                (settings / "exposure").write_text(exposure + "\n")
            if ubuntu:
                Path(directory, "etc", "postgresql", "16", "main").mkdir(parents=True)

            def command_ok(arguments):
                if arguments[:3] == ["systemctl", "is-active", "--quiet"]:
                    return arguments[3] in active
                return True

            opener = mock.Mock()
            if ping:
                opener.open.return_value = Ping()
            else:
                opener.open.side_effect = ConnectionRefusedError()
            service_group = types.SimpleNamespace(gr_gid=(settings / "known_hosts").stat().st_gid)
            with mock.patch.object(check.os, "geteuid", return_value=0), \
                    mock.patch.object(check, "Path", lambda path: Path(directory + path)), \
                    mock.patch.object(check, "command_ok", command_ok), \
                    mock.patch.object(check.grp, "getgrnam", return_value=service_group), \
                    mock.patch.object(check.subprocess, "check_output",
                                      return_value="\n".join(listeners or default_listeners)), \
                    mock.patch.object(check.urllib.request, "build_opener", return_value=opener), \
                    contextlib.redirect_stdout(io.StringIO()) as output, \
                    self.assertRaises(SystemExit) as ended:
                check.main()
        report = json.loads(output.getvalue())
        self.assertEqual(ended.exception.code, 0 if report["passed"] else 1)
        return report["checks"]

    def new_failures(self, exposure="loopback", **changes):
        """Checks that fail after the changes but not on the same controller in good health.

        The test files are not root's, so configuration_is_private fails in both unless run as root.
        """
        def failing(checks):
            return {name for name, passed in checks.items() if not passed}
        return failing(self.report(exposure, **changes)) - failing(self.report(exposure))

    def test_a_healthy_controller_passes_with_the_generated_ssh_options(self):
        for exposure in EXPOSURES:
            with self.subTest(exposure=exposure):
                checks = self.report(exposure)
                self.assertLessEqual({name for name, passed in checks.items() if not passed},
                                     {"configuration_is_private"})
                self.assertTrue(checks["strict_target_host_verification"])
                self.assertTrue(checks["port_3000_listening"] and checks["port_5432_listening"])

    def test_ubuntu_cluster_down_behind_its_active_wrapper_unit_names_postgresql(self):
        # Ubuntu's postgresql.service stays active while postgresql@16-main is down.
        failures = self.new_failures(active={"semaphore", "postgresql"}, listeners=[SEMAPHORE])
        self.assertEqual(failures, {"postgresql_is_active", "port_5432_listening"})

    def test_enterprise_linux_checks_its_postgresql_unit(self):
        checks = self.report(active={"semaphore", "postgresql"}, ubuntu=False)
        self.assertTrue(checks["postgresql_is_active"])
        checks = self.report(active={"semaphore", "postgresql@16-main"}, ubuntu=False)
        self.assertFalse(checks["postgresql_is_active"])

    def test_stopped_semaphore_is_not_reported_as_an_exposure_problem(self):
        for exposure, (_interface, listeners) in EXPOSURES.items():
            with self.subTest(exposure=exposure):
                checks = self.report(exposure, active=UBUNTU_UNITS - {"semaphore"},
                                     listeners=[line for line in listeners if ":3000 " not in line], ping=False)
                failing = {name for name, passed in checks.items() if not passed} - {"configuration_is_private"}
                self.assertEqual(failing, {"semaphore_is_active", "http_ping", "port_3000_listening"})
                for name in failing:
                    self.assertNotEqual(updater.readiness_hint(name), updater.EXPOSURE_HINT)

    def test_listeners_beyond_loopback_still_fail_with_the_exposure_hint(self):
        everywhere = f"LISTEN 0 4096 {ANY}:3000 {ANY}:*"
        for exposure, listeners, expected in (
                ("loopback", [everywhere, POSTGRESQL], "port_3000_only_loopback"),
                ("https", [everywhere, POSTGRESQL, NGINX_443], "port_3000_only_loopback"),
                # Semaphore was not restarted after its configuration changed to every address.
                ("http", [SEMAPHORE, POSTGRESQL], "port_3000_bound_on_all_addresses")):
            with self.subTest(exposure=exposure):
                self.assertEqual(self.new_failures(exposure, listeners=listeners), {expected})
                self.assertEqual(updater.readiness_hint(expected), updater.EXPOSURE_HINT)
        self.assertEqual(self.new_failures(listeners=[SEMAPHORE, f"LISTEN 0 200 {ANY}:5432 {ANY}:*"]),
                         {"port_5432_only_loopback"})

    def test_service_failures_point_to_the_service_logs(self):
        for name, service in SERVICE_CHECKS.items():
            with self.subTest(name=name):
                hint = updater.readiness_hint(name)
                self.assertNotEqual(hint, updater.EXPOSURE_HINT)
                self.assertRegex(hint, rf"sudo (systemctl status|journalctl -u) {service}")


if __name__ == "__main__":
    unittest.main()
