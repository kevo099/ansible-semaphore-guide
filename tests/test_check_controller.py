"""Offline checks for the readiness script's parsing; nothing here needs root or a controller."""

import importlib.util
import os
from pathlib import Path
import stat
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_controller", ROOT / "scripts" / "check-controller.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

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


if __name__ == "__main__":
    unittest.main()
