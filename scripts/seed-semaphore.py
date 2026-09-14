#!/usr/bin/env python3
"""Seed a fresh Semaphore controller with the guide's practice project.

Runs on the controller as root after the installer. It logs in with the
locally generated admin password, creates one project and its dependent
objects through the HTTP API on loopback, including the vendor STIG lessons,
and prints only names and numeric identifiers. It refuses to run twice.
"""

import argparse
import http.cookiejar
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:3000/api"
MARKER = Path("/etc/semaphore/.practice-project-seeded")

RECOVERY_PROMPT = [{
    "name": "recovery_snapshot_ack",
    "title": "Selected target recovery point",
    "description": "Snapshot or back up this exact target first. Vendor STIG remediation changes SSH, sudo, kernel and login policy.",
    "type": "enum",
    "required": True,
    "values": [{"name": "SNAPSHOT READY - apply the vendor STIG fixes to this target", "value": "SNAPSHOT READY"}],
}]

LESSONS = [
    # name, playbook, extra arguments, variable group, run prompt
    ("Ping", "playbooks/ping.yml", [], "Practice defaults", []),
    ("Baseline preview", "playbooks/baseline.yml", ["--check", "--diff"], "Practice defaults", []),
    ("Baseline apply", "playbooks/baseline.yml", ["--diff"], "Practice defaults", []),
    ("Users", "playbooks/users.yml", [], "Practice defaults", []),
    ("Webserver", "playbooks/webserver.yml", [], "Practice defaults", []),
    ("Patch preview", "playbooks/patch.yml", ["--check", "--diff"], "Practice defaults", []),
    ("Patch, no reboot", "playbooks/patch.yml", [], "Practice defaults", []),
    ("Patch, allow required reboot", "playbooks/patch.yml", [], "Allow required reboot", []),
    ("STIG audit (vendor scan only)", "playbooks/stig-audit.yml", [], "Practice defaults", []),
    ("STIG apply (vendor fixes, approval required)", "playbooks/stig-apply.yml", [], "Practice defaults", RECOVERY_PROMPT),
    ("STIG apply, allow required reboot", "playbooks/stig-apply.yml", [], "Allow required reboot", RECOVERY_PROMPT),
]

VARIABLE_GROUPS = {
    "Practice defaults": {},
    "Allow required reboot": {"allow_reboot": True},
}


def lab_dir_path(value):
    """The repository URL must be an absolute directory so Semaphore treats it as local."""
    path = Path(value)
    if not path.is_absolute() or str(path) == "/":
        raise ValueError("The lab folder must be an absolute path below /")
    return str(path)


def template_payload(project_id, ids, lesson):
    name, playbook, extra_args, group, prompt = lesson
    return {
        "project_id": project_id,
        "name": name,
        "app": "ansible",
        "playbook": playbook,
        "inventory_id": ids["inventory"],
        "repository_id": ids["repository"],
        "environment_id": ids["environments"][group],
        # The playbooks' preflight requires an explicit --limit; pass it as a CLI
        # argument, which this release applies, rather than the template limit field.
        "arguments": json.dumps(["--limit", "lab", *extra_args]),
        "limit": "",
        "type": "",
        "description": "Seeded by the guide; runs from the local lab folder.",
        "allow_override_args_in_task": False,
        "suppress_success_alerts": False,
        "survey_vars": prompt,
    }


def repository_payload(project_id, ids, lab_dir):
    return {"project_id": project_id, "name": "Local lab folder", "git_url": lab_dir,
            "git_branch": "main", "ssh_key_id": ids["none_key"]}


def inventory_payload(project_id, ids):
    return {"project_id": project_id, "name": "Lab inventory file", "type": "file",
            "inventory": "inventories/lab.ini", "repository_id": ids["repository"],
            "ssh_key_id": ids["ssh_key"]}


def environment_payloads(project_id):
    return {name: {"project_id": project_id, "name": name, "json": json.dumps(values), "env": "{}"}
            for name, values in VARIABLE_GROUPS.items()}


def seed_plan(project_id, ids, lab_dir, ssh_login):
    """Pure description of every object to create, in dependency order."""
    return {
        "key": {"project_id": project_id, "name": "Practice target SSH", "type": "ssh",
                "ssh": {"login": ssh_login, "passphrase": "", "private_key": "<read from key file>"}},
        "repository": repository_payload(project_id, ids, lab_dir),
        "inventory": inventory_payload(project_id, ids),
        "environments": environment_payloads(project_id),
        "templates": [template_payload(project_id, ids, lesson) for lesson in LESSONS],
    }


def parse_body(raw):
    """Semaphore answers JSON for objects but plain text for /ping; keep both."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            # Never echo the request body; it may hold credentials.
            raise SystemExit(f"{method} {path} failed with HTTP {error.code}") from None
        return parse_body(raw)


def wait_ready(client):
    for _ in range(30):
        try:
            client.call("GET", "/ping")
            return
        except (OSError, SystemExit):
            time.sleep(1)
    raise SystemExit("Semaphore did not answer /api/ping")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-dir", type=lab_dir_path, required=True)
    parser.add_argument("--key-file", type=Path, required=True, help="private automation key, root-only")
    parser.add_argument("--known-hosts", type=Path, required=True)
    parser.add_argument("--project-name", default="Ansible Practice")
    parser.add_argument("--ssh-login", default="svc_ansible")
    parser.add_argument("--admin-login", default="admin")
    args = parser.parse_args()

    if MARKER.exists():
        raise SystemExit("Practice project already seeded; manage further changes in the UI")
    for required in (args.key_file, args.known_hosts, Path(args.lab_dir) / "inventories" / "lab.ini"):
        if not required.is_file():
            raise SystemExit(f"Missing required file: {required}")
    private_key = args.key_file.read_text()
    if "PRIVATE KEY-----" not in private_key:
        raise SystemExit("The key file does not look like an OpenSSH private key")
    password = Path("/etc/semaphore/initial-admin-password").read_text().strip()

    client = Client(API)
    wait_ready(client)
    client.call("POST", "/auth/login", {"auth": args.admin_login, "password": password})

    existing = client.call("GET", "/projects") or []
    if any(project.get("name") == args.project_name for project in existing):
        raise SystemExit("A project with that name already exists; refusing to duplicate it")
    project = client.call("POST", "/projects", {"name": args.project_name, "max_parallel_tasks": 1, "alert": False})
    project_id = project["id"]

    keys = client.call("GET", f"/project/{project_id}/keys") or []
    none_keys = [key["id"] for key in keys if key.get("type") == "none"]
    if not none_keys:
        none_keys = [client.call("POST", f"/project/{project_id}/keys",
                                 {"project_id": project_id, "name": "None", "type": "none"})["id"]]
    ids = {"none_key": none_keys[0]}

    ids["ssh_key"] = client.call("POST", f"/project/{project_id}/keys", {
        "project_id": project_id, "name": "Practice target SSH", "type": "ssh",
        "ssh": {"login": args.ssh_login, "passphrase": "", "private_key": private_key},
    })["id"]
    ids["repository"] = client.call("POST", f"/project/{project_id}/repositories",
                                    repository_payload(project_id, ids, args.lab_dir))["id"]
    ids["environments"] = {}
    for name, body in environment_payloads(project_id).items():
        ids["environments"][name] = client.call("POST", f"/project/{project_id}/environment", body)["id"]
    ids["inventory"] = client.call("POST", f"/project/{project_id}/inventory", inventory_payload(project_id, ids))["id"]
    templates = {}
    for lesson in LESSONS:
        body = template_payload(project_id, ids, lesson)
        templates[body["name"]] = client.call("POST", f"/project/{project_id}/templates", body)["id"]

    MARKER.touch(mode=0o600, exist_ok=False)
    print(json.dumps({
        "project": {"name": args.project_name, "id": project_id},
        "repository": {"name": "Local lab folder", "path": args.lab_dir},
        "inventory": {"name": "Lab inventory file", "file": str(Path(args.lab_dir) / "inventories" / "lab.ini")},
        "templates": templates,
    }, indent=2))


if __name__ == "__main__":
    sys.exit(main())
