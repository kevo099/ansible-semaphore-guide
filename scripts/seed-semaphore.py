#!/usr/bin/env python3
"""Seed a fresh Semaphore controller with the guide's practice project, or update one.

Runs on the controller as root. Without --update, the installer runs it once: it
logs in with the locally generated admin password, creates one project and its
dependent objects through the HTTP API on loopback, including the vendor STIG
lessons, and prints only names and numeric identifiers. It refuses to run twice.

With --update, scripts/update-controller.sh runs it on a controller that is
already seeded: it adds the variable groups, template tabs and templates this
release seeds that the project lacks, and puts untabbed seeded templates on
their tab. It changes nothing else. --plan shows what an update would do.
"""

import argparse
import copy
import http.cookiejar
import json
import os
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

# Ansible options for each template. The playbooks' preflight requires an explicit
# limit; this release passes the template's Limit option to ansible-playbook as --limit.
ALL_LAB_TARGETS = {"limit": ["lab"]}
# STIG apply changes one approved target per run, so its Run dialog asks for the host.
ONE_TARGET_PER_RUN = {"limit": [], "allow_override_limit": True}
# A content file is written for one system, so its Run dialog asks for the matching hosts.
MATCHING_TARGETS = {"limit": [], "allow_override_limit": True}

LESSONS = [
    # name, playbook, extra arguments, variable group, run prompt, Ansible options
    ("Ping", "playbooks/ping.yml", [], "Practice defaults", [], ALL_LAB_TARGETS),
    ("Baseline preview", "playbooks/baseline.yml", ["--check", "--diff"], "Practice defaults", [], ALL_LAB_TARGETS),
    ("Baseline apply", "playbooks/baseline.yml", ["--diff"], "Practice defaults", [], ALL_LAB_TARGETS),
    ("Users", "playbooks/users.yml", [], "Practice defaults", [], ALL_LAB_TARGETS),
    ("Webserver", "playbooks/webserver.yml", [], "Practice defaults", [], ALL_LAB_TARGETS),
    ("Patch preview", "playbooks/patch.yml", ["--check", "--diff"], "Practice defaults", [], ALL_LAB_TARGETS),
    ("Patch, no reboot", "playbooks/patch.yml", [], "Practice defaults", [], ALL_LAB_TARGETS),
    ("Patch, allow required reboot", "playbooks/patch.yml", [], "Allow required reboot", [], ALL_LAB_TARGETS),
    ("STIG audit (vendor scan only)", "playbooks/stig-audit.yml", [], "Practice defaults", [], ALL_LAB_TARGETS),
    ("STIG apply (vendor fixes, approval required)", "playbooks/stig-apply.yml", [], "Practice defaults",
     RECOVERY_PROMPT, ONE_TARGET_PER_RUN),
    ("STIG apply, allow required reboot", "playbooks/stig-apply.yml", [], "Allow required reboot",
     RECOVERY_PROMPT, ONE_TARGET_PER_RUN),
    ("STIG audit, local SCAP content", "playbooks/stig-audit.yml", [], "Local SCAP content",
     [], MATCHING_TARGETS),
]

VARIABLE_GROUPS = {
    "Practice defaults": {},
    "Allow required reboot": {"allow_reboot": True},
    # Edit both values after copying a benchmark into the lab folder's content/;
    # the playbook refuses the placeholders.
    "Local SCAP content": {"stig_content_file": "content/REPLACE_WITH_BENCHMARK.xml",
                           "stig_content_profile": "REPLACE_WITH_PROFILE_ID"},
}


# Template tabs, which Semaphore calls views. Every seeded template belongs to one.
VIEWS = [
    ("Lessons", ["Ping", "Baseline preview", "Baseline apply", "Users", "Webserver"]),
    ("Patching", ["Patch preview", "Patch, no reboot", "Patch, allow required reboot"]),
    ("STIG", ["STIG audit (vendor scan only)", "STIG apply (vendor fixes, approval required)",
              "STIG apply, allow required reboot", "STIG audit, local SCAP content"]),
]
VIEW_OF = {name: title for title, names in VIEWS for name in names}


def lab_dir_path(value):
    """The repository URL must be an absolute directory so Semaphore treats it as local."""
    path = Path(value)
    if not path.is_absolute() or str(path) == "/":
        raise ValueError("The lab folder must be an absolute path below /")
    return str(path)


def template_payload(project_id, ids, lesson):
    name, playbook, extra_args, group, prompt, options = lesson
    one_target = options.get("allow_override_limit", False)
    return {
        "project_id": project_id,
        "name": name,
        "app": "ansible",
        "playbook": playbook,
        "inventory_id": ids["inventory"],
        "repository_id": ids["repository"],
        # environment_id is deprecated since Semaphore 2.18; a list replaces it.
        "environment_ids": [ids["environments"][group]],
        "arguments": json.dumps(extra_args),
        "task_params": copy.deepcopy(options),
        "description": ("Seeded by the guide; runs from the local lab folder. "
                        + ("Enter the hosts or group that the content file is written for in the Limit prompt."
                           if options is MATCHING_TARGETS
                           else "Enter exactly one host in the Limit prompt." if one_target
                           else "Limit: every host in the lab group.")),
        "allow_override_args_in_task": False,
        "suppress_success_alerts": False,
        "survey_vars": prompt,
        # Without a tab, Semaphore lists the template only under All.
        "view_id": ids.get("views", {}).get(VIEW_OF.get(name)),
    }


def repository_payload(project_id, ids, lab_dir):
    return {"project_id": project_id, "name": "Local lab folder", "git_url": lab_dir,
            "git_branch": "main", "ssh_key_id": ids["none_key"]}


def inventory_payload(project_id, ids):
    return {"project_id": project_id, "name": "Lab inventory file", "type": "file",
            "inventory": "inventories/lab.ini", "repository_id": ids["repository"],
            "ssh_key_id": ids["ssh_key"]}


def view_payloads(project_id, first_position=0):
    return {title: {"project_id": project_id, "title": title, "position": first_position + index}
            for index, (title, _names) in enumerate(VIEWS)}


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
        "views": view_payloads(project_id),
        "templates": [template_payload(project_id, ids, lesson) for lesson in LESSONS],
    }


def update_plan(existing):
    """Pure description of what an update adds, given the project's current objects.

    existing maps "environments" and "views" to sets of names, and "templates" to
    {name: view_id or None}. Objects that exist are never changed, except that a
    seeded template without a tab is put on its tab.
    """
    return {
        "environments": [name for name in VARIABLE_GROUPS if name not in existing["environments"]],
        "views": [title for title, _names in VIEWS if title not in existing["views"]],
        "templates": [lesson[0] for lesson in LESSONS if lesson[0] not in existing["templates"]],
        "tabs": sorted(name for name, view_id in existing["templates"].items()
                       if name in VIEW_OF and not view_id),
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
    def __init__(self, base, token=None):
        self.base = base
        self.token = token
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
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


def log_in(client, admin_login):
    """Use SEMAPHORE_API_TOKEN when set; otherwise the installer's admin password."""
    if client.token:
        client.call("GET", "/user")
        return
    password = Path("/etc/semaphore/initial-admin-password").read_text().strip()
    try:
        client.call("POST", "/auth/login", {"auth": admin_login, "password": password})
    except SystemExit:
        raise SystemExit("The installer's admin password no longer logs in. Create an API token "
                         "in the UI (your account menu, API Tokens) and run again with "
                         "SEMAPHORE_API_TOKEN set to it.") from None


def by_name(items, field="name"):
    return {item[field]: item for item in items or []}


def update(client, args):
    projects = by_name(client.call("GET", "/projects"))
    if args.project_name not in projects:
        raise SystemExit(f"No project named {args.project_name!r}; this controller was not seeded by the installer")
    project_id = projects[args.project_name]["id"]
    base = f"/project/{project_id}"
    repositories = by_name(client.call("GET", f"{base}/repositories"))
    inventories = by_name(client.call("GET", f"{base}/inventory"))
    for kind, found, name in (("repository", repositories, "Local lab folder"),
                              ("inventory", inventories, "Lab inventory file")):
        if name not in found:
            raise SystemExit(f"The project has no {kind} named {name!r}; add missing templates by hand")
    environments = by_name(client.call("GET", f"{base}/environment"))
    views = by_name(client.call("GET", f"{base}/views"), "title")
    templates = by_name(client.call("GET", f"{base}/templates"))
    plan = update_plan({
        "environments": set(environments),
        "views": set(views),
        "templates": {name: template.get("view_id") for name, template in templates.items()},
    })
    result = {"project": {"name": args.project_name, "id": project_id},
              "planned" if args.plan else "done": plan}
    if args.plan:
        print(json.dumps(result, indent=2))
        return

    ids = {"repository": repositories["Local lab folder"]["id"],
           "inventory": inventories["Lab inventory file"]["id"],
           "environments": {name: env["id"] for name, env in environments.items()},
           "views": {title: view["id"] for title, view in views.items()}}
    for name in plan["environments"]:
        body = environment_payloads(project_id)[name]
        ids["environments"][name] = client.call("POST", f"{base}/environment", body)["id"]
    new_views = view_payloads(project_id, first_position=len(views))
    for title in plan["views"]:
        ids["views"][title] = client.call("POST", f"{base}/views", new_views[title])["id"]
    for lesson in LESSONS:
        if lesson[0] in plan["templates"]:
            client.call("POST", f"{base}/templates", template_payload(project_id, ids, lesson))
    for name in plan["tabs"]:
        template_id = templates[name]["id"]
        template = client.call("GET", f"{base}/templates/{template_id}")
        template["view_id"] = ids["views"][VIEW_OF[name]]
        client.call("PUT", f"{base}/templates/{template_id}", template)
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-dir", type=lab_dir_path, required=True)
    parser.add_argument("--key-file", type=Path, help="private automation key, root-only (seeding only)")
    parser.add_argument("--known-hosts", type=Path, help="Semaphore's known_hosts file (seeding only)")
    parser.add_argument("--project-name", default="Ansible Practice")
    parser.add_argument("--ssh-login", default="svc_ansible")
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--update", action="store_true", help="add what this release seeds to a seeded project")
    parser.add_argument("--plan", action="store_true", help="with --update, only show what would change")
    args = parser.parse_args()

    if args.update:
        if not MARKER.exists():
            raise SystemExit("This controller was not seeded by the installer; there is no project to update")
        client = Client(API, os.environ.get("SEMAPHORE_API_TOKEN") or None)
        wait_ready(client)
        log_in(client, args.admin_login)
        update(client, args)
        return 0
    if args.plan:
        raise SystemExit("--plan applies only to --update")
    if args.key_file is None or args.known_hosts is None:
        raise SystemExit("Seeding needs --key-file and --known-hosts")

    if MARKER.exists():
        raise SystemExit("Practice project already seeded; manage further changes in the UI")
    for required in (args.key_file, args.known_hosts, Path(args.lab_dir) / "inventories" / "lab.ini"):
        if not required.is_file():
            raise SystemExit(f"Missing required file: {required}")
    private_key = args.key_file.read_text()
    if "PRIVATE KEY-----" not in private_key:
        raise SystemExit("The key file does not look like an OpenSSH private key")

    client = Client(API)
    wait_ready(client)
    log_in(client, args.admin_login)

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
    ids["views"] = {}
    for title, body in view_payloads(project_id).items():
        ids["views"][title] = client.call("POST", f"/project/{project_id}/views", body)["id"]
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
        "views": list(ids["views"]),
        "templates": templates,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
