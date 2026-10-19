#!/bin/sh
# Paste this WHOLE file into the TARGET VM's Azure Run Command > RunShellScript.
# It reads local information only and prints data: the VM's status, then the
# name=, address=, group= and fingerprint= lines to paste into
# scripts/add-target.sh --from-info in the guide's folder on the controller.
# It no longer takes the controller's lab folder (LAB_DIR): for a folder other
# than /opt/ansible-lab, add --lab-dir DIR to that command on the controller.
CONTROLLER_ADDRESS=''              # Set the controller IP to select the route's source address.
TARGET_ADDRESS=''                  # Optional: choose an assigned target IPv4 explicitly.
INVENTORY_NAME=''                  # Optional: otherwise use this VM's short hostname.

command -v python3 >/dev/null 2>&1 || {
    echo 'INFO FAILED: python3 is missing; finish the target bootstrap first.'
    exit 1
}
python3 - "$CONTROLLER_ADDRESS" "$TARGET_ADDRESS" "$INVENTORY_NAME" <<'PY_INFO'
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import socket
import subprocess
import sys

def run(args):
    try:
        return subprocess.run(
            args, text=True, capture_output=True, timeout=15,
            env=dict(os.environ, LC_ALL="C"),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Could not run " + args[0] + ": " + str(exc)) from exc

def require(ok, message):
    if not ok:
        raise ValueError(message)

def ipv4(value):
    address = ipaddress.ip_address(value)
    require(address.version == 4 and not (
        address.is_loopback or address.is_link_local or address.is_multicast
        or address.is_unspecified or int(address) == (1 << 32) - 1
    ), "Use a unicast target/controller IPv4 address.")
    return str(address)

def choose_address(controller, explicit, interfaces, routes):
    assigned = {
        info["local"] for interface in interfaces
        for info in interface.get("addr_info", [])
        if info.get("family") == "inet" and info.get("scope") == "global"
    }
    if explicit:
        selected = ipv4(explicit)
    elif controller:
        require(len(routes) == 1, "No unique route to the controller; set TARGET_ADDRESS.")
        selected = routes[0].get("prefsrc") or routes[0].get("src")
        require(bool(selected), "Route has no source IP; set TARGET_ADDRESS.")
    else:
        require(len(assigned) == 1, "Multiple/no IPv4 addresses; set CONTROLLER_ADDRESS or TARGET_ADDRESS.")
        selected = next(iter(assigned))
    selected = ipv4(selected)
    require(selected in assigned, "Selected target IP is not assigned to this VM.")
    require(selected != controller, "This appears to be the controller itself. Run on the TARGET.")
    return selected

def group_for(release):
    distro, version = release.get("ID", ""), release.get("VERSION_ID", "")
    if distro == "ubuntu" and version == "24.04":
        return "ubuntu"
    if distro in ("rhel", "almalinux", "rocky") and version.split(".")[0] == "9":
        return "enterprise_linux"
    raise ValueError("Guide targets supported here: Ubuntu 24.04 or RHEL/AlmaLinux/Rocky 9.")

def build_info(name, address, group, fingerprint):
    # Data, not a command: the controller does not trust this VM, so only its own
    # reviewed add-target.sh reads these values, and checks them again there.
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", name)),
            "INVENTORY_NAME must be a plain hostname, at most 63 characters.")
    ipv4(address)
    require(group in ("ubuntu", "enterprise_linux"), "Unsupported inventory group.")
    require(bool(re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", fingerprint)), "Invalid RSA fingerprint.")
    return ("Add this VM on the controller: in the guide's folder, run\n"
            "  sudo bash scripts/add-target.sh --from-info\n"
            "then paste these lines and press Ctrl-D:\n"
            "name=" + name + "\naddress=" + address + "\ngroup=" + group + "\nfingerprint=" + fingerprint + "\n")

def main(args):
    controller, explicit, requested_name = args
    controller = ipv4(controller) if controller else ""
    interfaces = run(["ip", "-j", "-4", "address", "show", "scope", "global"])
    require(interfaces.returncode == 0, "Cannot read the VM's network addresses.")
    routes = []
    if controller and not explicit:
        result = run(["ip", "-j", "-4", "route", "get", controller])
        require(result.returncode == 0, "No route to the controller; check networking or set TARGET_ADDRESS.")
        routes = json.loads(result.stdout)
    address = choose_address(controller, explicit, json.loads(interfaces.stdout), routes)
    release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            parsed = shlex.split(value)
            release[key] = parsed[0] if parsed else ""
    group = group_for(release)
    name = requested_name or socket.gethostname().split(".", 1)[0]
    hostkey = run(["ssh-keygen", "-l", "-E", "sha256", "-f", "/etc/ssh/ssh_host_rsa_key.pub"])
    require(hostkey.returncode == 0 and hostkey.stdout.rstrip().endswith("(RSA)"),
            "Cannot read the target's RSA host public key. Finish SSH setup first.")
    fingerprint = hostkey.stdout.split()[1]
    info = build_info(name, address, group, fingerprint)
    states = []
    try:
        account = pwd.getpwnam("svc_ansible")
        keys = Path(account.pw_dir) / ".ssh/authorized_keys"
        states.append("SSH keys present" if keys.is_file() and keys.stat().st_size else "WARNING: no authorized_keys")
        # The shadow entry, as onboard-linux.sh reads it; a set password is a crypt hash.
        shadow = run(["getent", "shadow", "svc_ansible"])
        fields = shadow.stdout.split(":")
        states.append("password set" if shadow.returncode == 0 and len(fields) > 1 and fields[1].startswith("$")
                      else "WARNING: password unset/locked/unverified")
    except KeyError:
        states.append("WARNING: svc_ansible is missing")
    try:
        sudo = run(["/usr/sbin/visudo", "-c"])
        states.append("sudo syntax OK" if sudo.returncode == 0 else "WARNING: sudo INVALID; run /usr/sbin/visudo -c on target")
    except ValueError:
        states.append("WARNING: sudo validation unavailable")
    summary = ("VM: " + name + " | " + address + " | " + release["ID"] + " " + release["VERSION_ID"]
               + "\nRSA: " + fingerprint + "\n" + "; ".join(states))
    output = summary + "\nInventory setup only; access still needs Ping/sudo testing.\n" + info
    # Azure action Run Command keeps the last 4 KB. Never emit a truncated line.
    require(len(output.encode()) <= 3900,
            "Output would exceed Azure's 4 KB limit. Shorten INVENTORY_NAME.")
    print(output, end="")

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ValueError, OSError, IndexError, json.JSONDecodeError) as exc:
        print("INFO FAILED: " + str(exc))
        sys.exit(1)
PY_INFO
