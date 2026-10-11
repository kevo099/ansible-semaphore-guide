#!/usr/bin/env python3
"""Seed a fresh Semaphore controller with the guide's practice project, or update one.

Runs on the controller as root. Without --update, the installer runs it once: it
logs in with the locally generated admin password, creates one project and its
dependent objects through the HTTP API on loopback, including the vendor STIG
lessons, and prints only names and numeric identifiers. It refuses to run twice.

With --update, scripts/update-controller.sh runs it on a controller that is
already seeded: it adds the variable groups, template tabs and templates this
release seeds that the project lacks, and puts untabbed seeded templates on
their tab. Seeded objects that this release replaces are reported and kept;
--remove-replaced deletes them. It changes nothing else. --plan shows what an
update would do.
"""

import argparse
import copy
import getpass
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

# One STIG tab per operating system and version, matching the playbook folders
# playbooks/stig/<system>/<version>/. Each audit runs on the system's inventory
# group, and the playbook skips hosts there that run another system. DISA
# publishes SCAP benchmarks for RHEL 9 and Ubuntu 24.04; their prefilled paths
# name the release chapter 9 tested, under the lab folder's content/ folder.
DISA_PROFILE = "xccdf_mil.disa.stig_profile_MAC-1_Classified"
STIG_SYSTEMS = [
    # label, playbook folder, inventory group, DISA SCAP benchmark in the lab folder
    ("RHEL 9", "rhel/9", "enterprise_linux", "content/rhel/9/U_RHEL_9_V2R9_STIG_SCAP_1-3_Benchmark.xml"),
    ("AlmaLinux 9", "almalinux/9", "enterprise_linux", None),
    ("Rocky Linux 9", "rocky/9", "enterprise_linux", None),
    ("Ubuntu 24.04", "ubuntu/24.04", "ubuntu", "content/ubuntu/24.04/U_CAN_Ubuntu_24-04_LTS_V1R5_STIG_SCAP_1-3_Benchmark.xml"),
]


def stig_tab(label):
    return f"STIG · {label}"


def disa_group(label):
    return f"DISA SCAP file · {label}"


def stig_lessons(label, folder, group, disa_file):
    audit, apply = f"playbooks/stig/{folder}/audit.yml", f"playbooks/stig/{folder}/apply.yml"
    lessons = [
        (f"{label} · STIG audit", audit, [], "Practice defaults", [], {"limit": [group]}),
        (f"{label} · STIG apply (approval required)", apply, [], "Practice defaults",
         RECOVERY_PROMPT, ONE_TARGET_PER_RUN),
        (f"{label} · STIG apply, allow required reboot", apply, [], "Allow required reboot",
         RECOVERY_PROMPT, ONE_TARGET_PER_RUN),
    ]
    if disa_file:
        lessons.append((f"{label} · STIG audit, DISA SCAP file", audit, [], disa_group(label), [],
                        {"limit": [group]}))
    return lessons


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
] + [lesson for system in STIG_SYSTEMS for lesson in stig_lessons(*system)]

VARIABLE_GROUPS = {
    "Practice defaults": {},
    "Allow required reboot": {"allow_reboot": True},
    # Copy the benchmark to this path in the lab folder, or edit the path for a
    # newer release; the playbook stops with an explanation while it is missing.
    **{disa_group(label): {"stig_content_file": disa_file, "stig_content_profile": DISA_PROFILE}
       for label, _folder, _group, disa_file in STIG_SYSTEMS if disa_file},
}


# Template tabs, which Semaphore calls views. Every seeded template belongs to one.
VIEWS = [
    ("Lessons", ["Ping", "Baseline preview", "Baseline apply", "Users", "Webserver"]),
    ("Patching", ["Patch preview", "Patch, no reboot", "Patch, allow required reboot"]),
] + [(stig_tab(system[0]), [lesson[0] for lesson in stig_lessons(*system)]) for system in STIG_SYSTEMS]
VIEW_OF = {name: title for title, names in VIEWS for name in names}

# What releases before 1.7.0 seeded and the per-system STIG tabs replace. Updates
# report these and keep them; --remove-replaced deletes them, which also deletes
# the templates' task history. The old templates still run the shared playbooks.
REPLACED_TEMPLATES = ["STIG audit (vendor scan only)", "STIG apply (vendor fixes, approval required)",
                      "STIG apply, allow required reboot", "STIG audit, local SCAP content"]
REPLACED_VIEWS = ["STIG"]
REPLACED_ENVIRONMENTS = ["Local SCAP content"]


def lab_dir_path(value):
    """The repository URL must be an absolute directory so Semaphore treats it as local."""
    path = Path(value)
    if not path.is_absolute() or str(path) == "/":
        raise ValueError("The lab folder must be an absolute path below /")
    return str(path)


def template_payload(project_id, ids, lesson):
    name, playbook, extra_args, group, prompt, options = lesson
    one_target = options.get("allow_override_limit", False)
    limit = ", ".join(options.get("limit", []))
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
                        + ("Enter exactly one host in the Limit prompt." if one_target
                           else "Limit: every host in the lab group." if limit == "lab"
                           else f"Limit: the {limit} group; hosts there that run another system are skipped.")),
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


def update_plan(existing, repository_id, inventory_id):
    """Pure description of what an update adds, given the project's current objects.

    existing holds lists as the API returns them: "environments", "views" (id,
    title, position) and "templates". Only templates bound to the lab folder's
    repository and inventory count as seeded; a template of yours with a seeded
    name elsewhere is never touched. Existing objects are never changed, except
    that a seeded template without a tab is put on its tab. Duplicate names that
    the update would have to choose between are reported and stop an apply.

    Seeded objects this release replaces are listed under "replaced": the old
    templates, and the old tab and variable group when nothing else uses them.
    Only apply_update(remove_replaced=True) deletes them.
    """
    env_names = [env["name"] for env in existing["environments"]]
    view_titles = [view["title"] for view in existing["views"]]
    seeded = [t for t in existing["templates"] if t["name"] in VIEW_OF
              and t.get("repository_id") == repository_id and t.get("inventory_id") == inventory_id]
    seeded_names = [t["name"] for t in seeded]
    duplicated = sorted({name for name in seeded_names if seeded_names.count(name) > 1})
    missing_templates = [lesson[0] for lesson in LESSONS if lesson[0] not in seeded_names]
    tabs = [{"id": t["id"], "name": t["name"]} for t in seeded
            if not t.get("view_id") and t["name"] not in duplicated]
    needed_views = {VIEW_OF[name] for name in missing_templates} | {VIEW_OF[t["name"]] for t in tabs}
    needed_envs = {lesson[3] for lesson in LESSONS if lesson[0] in missing_templates}
    ambiguous = sorted([f"variable group {name!r}" for name in needed_envs if env_names.count(name) > 1]
                       + [f"tab {title!r}" for title in needed_views if view_titles.count(title) > 1])
    replaced = [t for t in existing["templates"] if t["name"] in REPLACED_TEMPLATES
                and t.get("repository_id") == repository_id and t.get("inventory_id") == inventory_id]
    others = [t for t in existing["templates"] if t not in replaced]
    return {
        "environments": [name for name in VARIABLE_GROUPS if name not in env_names],
        "views": [title for title, _names in VIEWS if title not in view_titles],
        "templates": missing_templates,
        "tabs": sorted(tabs, key=lambda t: (t["name"], t["id"])),
        "duplicates": duplicated,
        "ambiguous": ambiguous,
        "replaced": {
            "templates": sorted(({"id": t["id"], "name": t["name"]} for t in replaced),
                                key=lambda t: (t["name"], t["id"])),
            "views": [{"id": v["id"], "title": v["title"]} for v in existing["views"]
                      if v["title"] in REPLACED_VIEWS and not any(t.get("view_id") == v["id"] for t in others)],
            "environments": [{"id": e["id"], "name": e["name"]} for e in existing["environments"]
                             if e["name"] in REPLACED_ENVIRONMENTS
                             and not any(e["id"] in environments_of(t) for t in others)],
        },
    }


def environments_of(template):
    """Every variable group a template links, under either of Semaphore's fields."""
    linked = set(template.get("environment_ids") or [])
    if template.get("environment_id"):
        linked.add(template["environment_id"])
    return linked


def replaced_names(plan):
    """The replaced objects of a plan as one readable list."""
    replaced = plan["replaced"]
    return ([f"template {t['name']!r}" for t in replaced["templates"]]
            + [f"tab {v['title']!r}" for v in replaced["views"]]
            + [f"variable group {e['name']!r}" for e in replaced["environments"]])


def first_free_position(views):
    return max((view.get("position") or 0 for view in views), default=-1) + 1


# The settings an update must never lose when it puts a template on a tab.
KEPT_FIELDS = ("name", "app", "playbook", "inventory_id", "repository_id", "environment_ids",
               "arguments", "task_params", "survey_vars", "vaults", "description", "type",
               "allow_override_args_in_task", "suppress_success_alerts")


def kept_settings(template):
    settings = {field: template.get(field) for field in KEPT_FIELDS}
    settings["environment_ids"] = sorted(settings["environment_ids"] or [])
    return settings


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


def log_in(client, admin_login, ask=False):
    """Use SEMAPHORE_API_TOKEN when set, otherwise the installer's admin password.

    With ask, a password that is missing or no longer works (changed in the UI)
    is asked for at the terminal, without echo; it goes only to Semaphore on loopback.
    """
    if client.token:
        client.call("GET", "/user")
        return
    try:
        password = Path("/etc/semaphore/initial-admin-password").read_text().strip()
    except OSError:
        password = None
    if password is not None:
        try:
            client.call("POST", "/auth/login", {"auth": admin_login, "password": password})
            return
        except SystemExit:
            pass
    if not (ask and sys.stdin.isatty()):
        raise SystemExit("The installer's admin password is missing or no longer logs in. Run this "
                         "from a terminal to be asked for a Semaphore administrator's login and "
                         "password, or set SEMAPHORE_API_TOKEN to an API token. Nothing was changed.")
    print("The installer's admin password is missing or no longer logs in (changed in the UI?).",
          file=sys.stderr)
    try:
        login = input(f"Semaphore administrator login [{admin_login}]: ").strip() or admin_login
        password = getpass.getpass("Password: ")
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("\nNo login given; nothing was changed.") from None
    try:
        client.call("POST", "/auth/login", {"auth": login, "password": password})
    except SystemExit:
        raise SystemExit("That login and password did not work; nothing was changed.") from None


def exactly_one(items, what, hint):
    if len(items) != 1:
        found = ", ".join(str(item["id"]) for item in items) or "none"
        raise SystemExit(f"Expected one {what}, found {len(items)} (IDs: {found}). {hint} Nothing was changed.")
    return items[0]


def resolve(client, project_name, lab_dir, project_id=None):
    """Find the seeded project and its lab folder objects by what they are, not only by name."""
    projects = client.call("GET", "/projects") or []
    matches = ([p for p in projects if p["id"] == project_id] if project_id
               else [p for p in projects if p.get("name") == project_name])
    project = exactly_one(matches, f"project named {project_name!r}",
                          "Pass --project-id with the ID of the seeded one.")
    base = f"/project/{project['id']}"
    repository = exactly_one(
        [r for r in client.call("GET", f"{base}/repositories") or []
         if (r.get("git_url") or "").rstrip("/") == lab_dir.rstrip("/")],
        f"repository whose URL is the lab folder {lab_dir}", "Check --lab-dir.")
    inventory = exactly_one(
        [i for i in client.call("GET", f"{base}/inventory") or []
         if i.get("type") == "file" and i.get("repository_id") == repository["id"]
         and i.get("inventory") == "inventories/lab.ini"],
        "file inventory inventories/lab.ini in that repository", "Add missing templates by hand.")
    return {
        "project": project, "base": base, "repository": repository, "inventory": inventory,
        "environments": client.call("GET", f"{base}/environment") or [],
        "views": client.call("GET", f"{base}/views") or [],
        "templates": client.call("GET", f"{base}/templates") or [],
    }


def plan_for(found):
    return update_plan({key: found[key] for key in ("environments", "views", "templates")},
                       found["repository"]["id"], found["inventory"]["id"])


def pending_edits(backup_dir):
    """Template edits an earlier update began but could not confirm; each blocks an apply."""
    found = []
    for path in sorted(backup_dir.glob("pending-template-*.json")):
        try:
            name = json.loads(path.read_text()).get("name", "?")
        except (OSError, ValueError):
            name = "?"
        found.append({"name": name, "record": str(path)})
    return found


def save_verified(client, path, before, desired, backup_dir):
    """PUT desired and confirm every kept setting; otherwise put before back and stop.

    A record of the template as it was is written first and removed only once the
    result is confirmed, so an edit that could not be confirmed stops later runs
    until you have checked that template.
    """
    record = backup_dir / f"pending-template-{before['id']}.json"
    with open(os.open(record, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
        json.dump(before, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    failed = None
    try:
        client.call("PUT", path, desired)
        if kept_settings(client.call("GET", path)) == kept_settings(desired):
            record.unlink()
            return
    except SystemExit as error:
        failed = error
    try:
        client.call("PUT", path, before)
        restored = kept_settings(client.call("GET", path)) == kept_settings(before)
    except SystemExit:
        restored = False
    if restored:
        record.unlink()
        state = "its settings were put back"
    else:
        state = f"compare it in the UI with {record}, which holds it as it was, then delete that file"
    raise SystemExit(f"Semaphore did not save template {desired['name']!r} as intended"
                     + (f" ({failed})" if failed else "") + f"; {state}. Stopped there; run the update again "
                     "once the cause is fixed.")


def remove_replaced_objects(client, base, plan, repository_id, inventory_id, say):
    """Delete what the plan lists as replaced, checking each object again first."""
    for template in plan["replaced"]["templates"]:
        current = client.call("GET", f"{base}/templates/{template['id']}")
        if (current.get("name") != template["name"] or current.get("repository_id") != repository_id
                or current.get("inventory_id") != inventory_id):
            say(f"Kept template {template['name']!r}: it changed since the plan")
            continue
        client.call("DELETE", f"{base}/templates/{template['id']}")
        say(f"Removed template {template['name']!r} and its task history")
    remaining = [client.call("GET", f"{base}/templates/{t['id']}")
                 for t in client.call("GET", f"{base}/templates") or []]
    for view in plan["replaced"]["views"]:
        if any(t.get("view_id") == view["id"] for t in remaining):
            say(f"Kept tab {view['title']!r}: other templates are on it")
            continue
        client.call("DELETE", f"{base}/views/{view['id']}")
        say(f"Removed tab {view['title']!r}")
    for environment in plan["replaced"]["environments"]:
        if any(environment["id"] in environments_of(t) for t in remaining):
            say(f"Kept variable group {environment['name']!r}: other templates use it")
            continue
        client.call("DELETE", f"{base}/environment/{environment['id']}")
        say(f"Removed variable group {environment['name']!r}")


def apply_update(client, found, plan, backup_dir, say=print, remove_replaced=False):
    """Add what the plan lists, and with remove_replaced delete what it replaces.

    Returns the path of the template backup, if one was taken.
    """
    if plan["ambiguous"]:
        raise SystemExit("Several objects share a name the update needs: " + "; ".join(plan["ambiguous"])
                         + ". Rename or remove the extra ones, then run again. Nothing was changed.")
    pending = pending_edits(backup_dir)
    if pending:
        raise SystemExit("An earlier update could not confirm its edit of " + ", ".join(
            f"{item['name']!r} (see {item['record']})" for item in pending)
            + ". Check that template in the UI, delete the record, and run again. Nothing was changed.")
    base, project_id = found["base"], found["project"]["id"]
    backup = None
    removing = remove_replaced and any(plan["replaced"].values())
    if plan["tabs"] or removing:
        # Semaphore rewrites a template's variable-group links when it saves one, and
        # deleting a template deletes it for good; keep every template as it was,
        # root-only, before changing any of them.
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Names sort by time, and two runs in one second never share one.
        stamp = time.time_ns()
        backup = backup_dir / f"semaphore-templates-{time.strftime('%Y%m%dT%H%M%S', time.localtime(stamp // 10**9))}-{stamp % 10**9:09d}.json"
        details = [client.call("GET", f"{base}/templates/{t['id']}") for t in found["templates"]]
        with open(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            json.dump(details, handle, indent=2)
        say(f"Templates as they were before: {backup}")

    ids = {"repository": found["repository"]["id"], "inventory": found["inventory"]["id"],
           "environments": {env["name"]: env["id"] for env in found["environments"]},
           "views": {view["title"]: view["id"] for view in found["views"]}}
    for name in plan["environments"]:
        body = environment_payloads(project_id)[name]
        ids["environments"][name] = client.call("POST", f"{base}/environment", body)["id"]
    position = first_free_position(found["views"])
    for title in plan["views"]:
        body = {"project_id": project_id, "title": title, "position": position}
        ids["views"][title] = client.call("POST", f"{base}/views", body)["id"]
        position += 1
    for lesson in LESSONS:
        if lesson[0] in plan["templates"]:
            client.call("POST", f"{base}/templates", template_payload(project_id, ids, lesson))
    for tab in plan["tabs"]:
        path = f"{base}/templates/{tab['id']}"
        before = client.call("GET", path)
        if before.get("view_id"):
            say(f"Kept the tab you gave {tab['name']!r} meanwhile")
            continue
        save_verified(client, path, before, dict(before, view_id=ids["views"][VIEW_OF[tab["name"]]]), backup_dir)
    if removing:
        remove_replaced_objects(client, base, plan, ids["repository"], ids["inventory"], say)
    return backup


def update(client, args):
    """--update for seed-semaphore.py itself; update-controller.py calls the parts directly."""
    found = resolve(client, args.project_name, args.lab_dir, getattr(args, "project_id", None))
    plan = plan_for(found)
    result = {"project": {"name": found["project"]["name"], "id": found["project"]["id"]},
              "planned" if args.plan else "done": plan}
    if not args.plan:
        backup = apply_update(client, found, plan, Path("/root/ansible-lab-update"), say=lambda _text: None,
                              remove_replaced=args.remove_replaced)
        if backup:
            result["template_backup"] = str(backup)
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
    parser.add_argument("--project-id", type=int, help="with --update, the seeded project's ID when names repeat")
    parser.add_argument("--remove-replaced", action="store_true",
                        help="with --update, delete the seeded objects this release replaces, "
                             "including the old templates' task history")
    args = parser.parse_args()

    if args.update:
        if not MARKER.exists():
            raise SystemExit("This controller was not seeded by the installer; there is no project to update")
        client = Client(API, os.environ.get("SEMAPHORE_API_TOKEN") or None)
        wait_ready(client)
        log_in(client, args.admin_login, ask=True)
        update(client, args)
        return 0
    if args.plan or args.remove_replaced:
        raise SystemExit("--plan and --remove-replaced apply only to --update")
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
