#!/bin/sh
# Paste this WHOLE file into the TARGET VM's Azure Run Command > RunShellScript.
# It reads local information only. It prints a separate command for the controller.
CONTROLLER_ADDRESS=''              # Set the controller IP to select the route's source address.
TARGET_ADDRESS=''                  # Optional: choose an assigned target IPv4 explicitly.
INVENTORY_NAME=''                  # Optional: otherwise use this VM's short hostname.
LAB_DIR='/opt/ansible-lab'           # The controller's seeded lab folder.

command -v python3 >/dev/null 2>&1 || {
    echo 'INFO FAILED: python3 is missing; finish the target bootstrap first.'
    exit 1
}
python3 - "$CONTROLLER_ADDRESS" "$TARGET_ADDRESS" "$INVENTORY_NAME" "$LAB_DIR" <<'PY_INFO'
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

# This code is PRINTED, never executed on the target.
CONTROLLER_CODE = r"""from pathlib import Path
import re, shlex, shutil, subprocess, time
name, address, group, wanted, folder = __DATA__
def stop(message):
    raise SystemExit("STOP: " + message)
def run(args, data=None):
    return subprocess.run(args, input=data, text=True, capture_output=True, timeout=20)
def fingerprint(line):
    result = run(["ssh-keygen", "-l", "-E", "sha256", "-f", "-"], line + "\n")
    return result.stdout.split()[1] if result.returncode == 0 else ""
inventory = Path(folder) / "inventories/lab.ini"
trust = Path("/etc/semaphore/known_hosts")
for path in (inventory, trust):
    if path.is_symlink() or not path.is_file():
        stop("Expected an existing regular file: " + str(path))
original = {p: p.read_text() for p in (inventory, trust)}
lines = original[inventory].splitlines()
section = ""
headers, existing = [], []
children = []
for i, line in enumerate(lines):
    clean = line.split("#", 1)[0].strip()
    header = re.fullmatch(r"\[([^]]+)\]", clean)
    if header:
        section = header[1]
        if section == group:
            headers.append(i)
        continue
    if section == "lab:children":
        children.append(clean)
    if not clean or ":" in section:
        continue
    tokens = shlex.split(clean)
    if tokens[0] == name:
        existing.append((section, clean))
    elif "ansible_host=" + address in tokens:
        stop("This address already has another inventory name; review it first.")
entry = name + " ansible_host=" + address
if len(headers) != 1 or group not in children:
    stop("Inventory must contain [" + group + "] and list it in [lab:children].")
if existing and existing != [(group, entry)]:
    stop("This inventory name already has different settings; review it first.")
scan = run(["ssh-keyscan", "-T", "5", "-t", "rsa", "--", address])
matching = [s for s in scan.stdout.splitlines() if s and not s.startswith("#") and fingerprint(s) == wanted]
if not matching:
    stop("SSH on port 22 did not return the target's RSA fingerprint. No files changed.")
lookup = run(["ssh-keygen", "-F", address, "-f", str(trust)])
if lookup.returncode not in (0, 1):
    stop("Could not inspect existing SSH trust.")
keys = [s for s in lookup.stdout.splitlines() if s and not s.startswith("#")]
if any(s.startswith("@") or (s.split()[1] == "ssh-rsa" and fingerprint(s) != wanted) for s in keys):
    stop("Existing RSA host trust conflicts. Verify any rebuild before replacing it.")
changes = {}
if not existing:
    lines.insert(headers[0] + 1, entry)
    changes[inventory] = "\n".join(lines) + "\n"
if not any(fingerprint(s) == wanted for s in keys):
    changes[trust] = original[trust].rstrip("\n") + "\n" + matching[0] + "\n"
stamp = ".before-add-" + str(time.time_ns())
for path in changes:
    shutil.copy2(path, str(path) + stamp)
try:
    for path, content in changes.items():
        path.write_text(content)
except Exception:
    for path in changes:
        path.write_text(original[path])
    raise
print("Added " + name if changes else "Already present: " + name)
print("Inventory: " + str(inventory))
print("Next: select the SSH/sudo credentials in Semaphore; run Ping for " + name)
"""
# The trust path matches both seeded controller installers.

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

def build_command(name, address, group, fingerprint, folder):
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", name)),
            "INVENTORY_NAME must be a plain hostname, at most 63 characters.")
    ipv4(address)
    require(group in ("ubuntu", "enterprise_linux"), "Unsupported inventory group.")
    require(bool(re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", fingerprint)), "Invalid RSA fingerprint.")
    require(Path(folder).is_absolute() and "\n" not in folder and len(folder) <= 200,
            "LAB_DIR must be an absolute controller path, at most 200 characters.")
    data = repr((name, address, group, fingerprint, folder))
    code = CONTROLLER_CODE.replace("__DATA__", data)
    return "sudo python3 - <<'ADD_ANSIBLE_TARGET'\n" + code + "ADD_ANSIBLE_TARGET\n"

def main(args):
    controller, explicit, requested_name, folder = args
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
    command = build_command(name, address, group, fingerprint, folder)
    states = []
    try:
        account = pwd.getpwnam("svc_ansible")
        keys = Path(account.pw_dir) / ".ssh/authorized_keys"
        states.append("SSH keys present" if keys.is_file() and keys.stat().st_size else "WARNING: no authorized_keys")
        password = run(["passwd", "-S", "svc_ansible"])
        status = password.stdout.split()
        states.append("password set" if password.returncode == 0 and len(status) > 1 and status[1] in ("P", "PS")
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
    output = summary + "\nInventory setup only; access still needs Ping/sudo testing.\nCOPY THE FOLLOWING BLOCK INTO THE CONTROLLER CONSOLE:\n" + command
    # Azure action Run Command keeps the last 4 KB. Never emit a truncated command.
    require(len(output.encode()) <= 3900,
            "Output would exceed Azure's 4 KB limit. Shorten INVENTORY_NAME/LAB_DIR.")
    print(output, end="")

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ValueError, OSError, IndexError, json.JSONDecodeError) as exc:
        print("INFO FAILED: " + str(exc))
        sys.exit(1)
PY_INFO
