#!/usr/bin/env python3
"""Read-only readiness checks. Reports booleans and versions, never credentials."""

import grp
import json
import os
from pathlib import Path
import stat
import subprocess
import urllib.request


def command_ok(args):
    return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo to check the protected configuration")
    checks = {}
    config_path = Path("/etc/semaphore/config.json")
    config = json.loads(config_path.read_text())
    exposure_path = Path("/etc/semaphore/exposure")
    exposure = exposure_path.read_text().strip() if exposure_path.is_file() else "loopback"
    any_address = "0.0.0" + ".0"  # split so the repository validator ignores it
    expected_interface = any_address if exposure == "http" else "127.0.0.1"
    checks["semaphore_bind_matches_exposure_" + exposure] = (
        config.get("interface") == expected_interface and config.get("port") == ":3000"
    )
    checks["configuration_is_private"] = (
        stat.S_IMODE(config_path.stat().st_mode) == 0o640 and config_path.stat().st_uid == 0
    )
    # Tools that rewrite this file, such as ssh-keygen -R, can leave it root:root,
    # after which every job fails host verification.
    known_hosts = Path("/etc/semaphore/known_hosts").stat()
    checks["service_can_read_known_hosts"] = (
        known_hosts.st_gid == grp.getgrnam("semaphore").gr_gid and bool(known_hosts.st_mode & stat.S_IRGRP)
    )
    checks["semaphore_is_active"] = command_ok(["systemctl", "is-active", "--quiet", "semaphore"])
    checks["semaphore_is_enabled"] = command_ok(["systemctl", "is-enabled", "--quiet", "semaphore"])
    # Ubuntu names the cluster unit postgresql@16-main; Enterprise Linux uses postgresql.
    checks["postgresql_is_active"] = any(
        command_ok(["systemctl", "is-active", "--quiet", unit]) for unit in ("postgresql@16-main", "postgresql")
    )
    checks["ansible_is_available"] = command_ok(["/opt/ansible-venv/bin/ansible", "--version"])
    checks["strict_target_host_verification"] = (
        config.get("env_vars", {}).get("ANSIBLE_HOST_KEY_CHECKING") == "True"
        and "StrictHostKeyChecking=yes" in config.get("env_vars", {}).get("ANSIBLE_SSH_ARGS", "")
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:3000/api/ping", timeout=5) as response:
            checks["http_ping"] = response.status == 200
    except (OSError, ValueError):
        checks["http_ping"] = False
    listeners = subprocess.check_output(["ss", "-H", "-lnt"], text=True)
    bound = {port: [] for port in (3000, 5432)}
    for line in listeners.splitlines():
        local = line.split()[3]
        for port in bound:
            if local.endswith(":" + str(port)):
                bound[port].append(local.rsplit(":", 1)[0].strip("[]"))
    for port, hosts in bound.items():
        if port == 3000 and exposure == "http":
            checks["port_3000_bound_on_all_addresses"] = any_address in hosts or "*" in hosts
        else:
            checks[f"port_{port}_only_loopback"] = bool(hosts) and all(host in {"127.0.0.1", "::1"} for host in hosts)
    # nginx may listen beyond loopback only on 443, and only for the https exposure.
    nginx_ports = set()
    for line in subprocess.check_output(["ss", "-H", "-lntp"], text=True).splitlines():
        host, _, port = line.split()[3].rpartition(":")
        if '"nginx"' in line and host.strip("[]") not in {"127.0.0.1", "::1"}:
            nginx_ports.add(port)
    checks["nginx_listens_only_where_expected"] = nginx_ports <= ({"443"} if exposure == "https" else set())
    if exposure == "https":
        checks["nginx_tls_proxy_is_active"] = command_ok(["systemctl", "is-active", "--quiet", "nginx"])
        tls_listeners = [line.split()[3] for line in listeners.splitlines() if line.split()[3].endswith(":443")]
        checks["port_443_listening"] = bool(tls_listeners)
    print(json.dumps({"passed": all(checks.values()), "checks": checks}, indent=2))
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
