#!/usr/bin/env python3
"""Read-only readiness checks. Reports booleans and versions, never credentials."""

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
    checks["semaphore_bind_is_loopback"] = config.get("interface") == "127.0.0.1" and config.get("port") == ":3000"
    checks["configuration_is_private"] = (
        stat.S_IMODE(config_path.stat().st_mode) == 0o640 and config_path.stat().st_uid == 0
    )
    checks["semaphore_is_active"] = command_ok(["systemctl", "is-active", "--quiet", "semaphore"])
    checks["semaphore_is_enabled"] = command_ok(["systemctl", "is-enabled", "--quiet", "semaphore"])
    checks["postgresql_is_active"] = command_ok(["systemctl", "is-active", "--quiet", "postgresql@16-main"])
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
        checks[f"port_{port}_only_loopback"] = bool(hosts) and all(host in {"127.0.0.1", "::1"} for host in hosts)
    print(json.dumps({"passed": all(checks.values()), "checks": checks}, indent=2))
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
