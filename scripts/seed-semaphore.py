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
--remove-replaced deletes them, except a template that a schedule or
integration still runs. It changes nothing else. --plan shows what an update
would do.
"""

import argparse
import copy
import getpass
import http.client
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:3000/api"
MARKER = Path("/etc/semaphore/.practice-project-seeded")
PASSWORD_FILE = Path("/etc/semaphore/initial-admin-password")
# Root-only template backups and records of unconfirmed edits, kept by updates.
BACKUP_DIR = Path("/root/ansible-lab-update")
# Semaphore's project permission to change templates, tabs and variable groups
# (CanManageProjectResources): owners and managers have it; administrators need none.
CAN_MANAGE_PROJECT_RESOURCES = 4

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

# What releases before 1.7.0 seeded and the per-system STIG tabs replace, with the
# name that each system's replacement has after "<system> · ". Updates report
# these and keep them; --remove-replaced deletes them, which also deletes the
# templates' task history. Semaphore would delete a template's schedules and
# integrations with it too, so a template that any of them runs is kept. The old
# templates still run the shared playbooks.
REPLACED_BY = {"STIG audit (vendor scan only)": "STIG audit",
               "STIG apply (vendor fixes, approval required)": "STIG apply (approval required)",
               "STIG apply, allow required reboot": "STIG apply, allow required reboot",
               "STIG audit, local SCAP content": "STIG audit, DISA SCAP file"}
REPLACED_TEMPLATES = list(REPLACED_BY)
REPLACED_VIEWS = ["STIG"]
# A replaced variable group is removed only while it still holds what was seeded;
# one you filled in keeps your values until you delete it yourself.
REPLACED_ENVIRONMENTS = {"Local SCAP content": {"stig_content_file": "content/REPLACE_WITH_BENCHMARK.xml",
                                                "stig_content_profile": "REPLACE_WITH_PROFILE_ID"}}


def lab_dir_path(value):
    """The repository URL must be an absolute directory so Semaphore treats it as local."""
    path = Path(value)
    if not path.is_absolute() or str(path) == "/":
        raise ValueError("The lab folder must be an absolute path below /")
    return str(path)


def template_payload(project_id, ids, lesson, vaults=()):
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
        "vaults": [dict(vault) for vault in vaults],
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
    title, position) and "templates", and "triggers", what triggers_of() found
    for the replaced templates. Only templates bound to the lab folder's
    repository and inventory count as seeded; a template of yours with a seeded
    name elsewhere is never touched. Existing objects are never changed, except
    that a seeded template without a tab is put on its tab. Duplicate names that
    the update would have to choose between are reported and stop an apply.

    Seeded objects this release replaces are listed under "replaced": the old
    templates, and the old tab and variable group when nothing else uses them.
    A replaced template that a schedule or integration runs, or whose schedules
    and integrations could not be read, is listed under "in_use" instead, and
    kept. A replaced variable group you filled in is listed under "edited"
    instead, and kept. Only remove_replaced() deletes anything.
    """
    env_names = [env["name"] for env in existing["environments"]]
    view_titles = [view["title"] for view in existing["views"]]
    seeded = lab_templates(existing["templates"], VIEW_OF, repository_id, inventory_id)
    seeded_names = [t["name"] for t in seeded]
    duplicated = sorted({name for name in seeded_names if seeded_names.count(name) > 1})
    missing_templates = [lesson[0] for lesson in LESSONS if lesson[0] not in seeded_names]
    tabs = [{"id": t["id"], "name": t["name"]} for t in seeded
            if not t.get("view_id") and t["name"] not in duplicated]
    needed_views = {VIEW_OF[name] for name in missing_templates} | {VIEW_OF[t["name"]] for t in tabs}
    needed_envs = {lesson[3] for lesson in LESSONS if lesson[0] in missing_templates}
    ambiguous = sorted([f"variable group {name!r}" for name in needed_envs if env_names.count(name) > 1]
                       + [f"tab {title!r}" for title in needed_views if view_titles.count(title) > 1])
    triggers = existing.get("triggers", {})
    candidates = lab_templates(existing["templates"], REPLACED_TEMPLATES, repository_id, inventory_id)
    in_use = [t for t in candidates if triggered(triggers.get(t["id"]))]
    replaced = [t for t in candidates if t not in in_use]
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
                             if e["name"] in REPLACED_ENVIRONMENTS and not edited(e)
                             and not any(e["id"] in environments_of(t) for t in others)],
        },
        "in_use": sorted(({"id": t["id"], "name": t["name"], **trigger_names(triggers.get(t["id"]))}
                          for t in in_use), key=lambda t: (t["name"], t["id"])),
        "edited": [e["name"] for e in existing["environments"] if e["name"] in REPLACED_ENVIRONMENTS and edited(e)],
    }


def lab_templates(templates, names, repository_id, inventory_id):
    """The templates with these names that run from the lab folder's repository and inventory."""
    return [t for t in templates if t["name"] in names
            and t.get("repository_id") == repository_id and t.get("inventory_id") == inventory_id]


def triggered(runs):
    """Whether a replaced template must stay: something runs it, or that could not be read."""
    return runs is None or bool(runs.get("error") or runs.get("schedules") or runs.get("integrations"))


def trigger_names(runs):
    """What triggers_of() found for one template, reduced to IDs and names."""
    if runs is None or runs.get("error"):
        return {"error": (runs or {}).get("error") or "not checked"}
    return {kind: [{"id": item["id"], "name": item.get("name") or ""} for item in runs[kind]]
            for kind in ("schedules", "integrations")}


def edited(environment):
    """Whether a replaced variable group holds anything but the values it was seeded with."""
    try:
        values = json.loads(environment.get("json") or "")
    except ValueError:
        return True
    try:
        variables = json.loads(environment.get("env") or "{}")
    except ValueError:
        return True
    return values != REPLACED_ENVIRONMENTS[environment["name"]] or variables != {}


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


def in_use_names(plan):
    """The replaced templates that stay because something runs them, as readable lines."""
    return [f"template {t['name']!r}: {why_kept(t)}" for t in plan["in_use"]]


def successors(name):
    """The per-system templates that replace an old seeded template."""
    return [lesson[0] for lesson in LESSONS if lesson[0].endswith(f" · {REPLACED_BY[name]}")]


def why_kept(template):
    """Why a replaced template stays, from its trigger_names(), and what to do about it."""
    if template.get("error"):
        return (f"its schedules and integrations could not be read ({template['error']}), and Semaphore "
                "would delete them with it")
    uses = [f"{kind} {item['name']!r} (ID {item['id']})" if item["name"] else f"{kind} ID {item['id']}"
            for kind, items in (("schedule", template["schedules"]), ("integration", template["integrations"]))
            for item in items]
    return (f"{', '.join(uses)} {'runs' if len(uses) == 1 else 'run'} it. Move its schedules and integrations "
            f"to the per-system templates that replace it, such as {successors(template['name'])[0]!r}, "
            "then run the update with --remove-replaced")


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


def error_reason(raw):
    """Semaphore's reason for refusing a request: the "error" field of its JSON answer, shortened."""
    try:
        reason = json.loads(raw).get("error")
    except (ValueError, AttributeError):
        return ""
    if not isinstance(reason, str):
        return ""
    reason = " ".join("".join(c if c.isprintable() else " " for c in reason).split())
    return reason if len(reason) <= 200 else reason[:197] + "..."


class ApiError(SystemExit):
    """Semaphore refused a request; the message gives its reason, never the request body."""

    def __init__(self, method, path, status, reason=""):
        super().__init__(f"{method} {path} failed with HTTP {status}" + (f": {reason}" if reason else ""))
        self.status, self.reason = status, reason


class Client:
    def __init__(self, base, token=None):
        self.base = base
        self.token = token
        # Semaphore marks its session cookie Secure when its web_host is https. On
        # loopback, plain http never leaves the controller, so the cookie goes back too.
        loopback = urllib.parse.urlsplit(base).hostname in ("127.0.0.1", "::1")
        policy = http.cookiejar.DefaultCookiePolicy(
            secure_protocols=("https", "wss", "http") if loopback else ("https", "wss"))
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar(policy))
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
            # Show Semaphore's own reason from its answer. Never echo the request body;
            # it may hold credentials.
            try:
                answer = error.read(4096)
            except (OSError, http.client.HTTPException):
                answer = b""
            raise ApiError(method, path, error.code, error_reason(answer)) from None
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
    """Log in and return the user as GET /user describes it.

    Uses SEMAPHORE_API_TOKEN when set, otherwise the installer's admin password.
    With ask, a password that is missing or no longer works (changed in the UI)
    is asked for at the terminal, without echo; it goes only to Semaphore on loopback.
    """
    if client.token:
        try:
            return client.call("GET", "/user")
        except ApiError as error:
            if error.status != 401:
                raise
            raise SystemExit("Semaphore does not accept SEMAPHORE_API_TOKEN: the token is wrong, expired or "
                             "deleted. Nothing was changed.") from None
    try:
        password = PASSWORD_FILE.read_text().strip()
    except OSError:
        password = None
    if password is not None:
        try:
            client.call("POST", "/auth/login", {"auth": admin_login, "password": password})
        except SystemExit:
            pass
        else:
            return session_user(client)
    if not (ask and sys.stdin.isatty()):
        raise SystemExit("The installer's admin password is missing or no longer logs in. Run this "
                         "from a terminal to be asked for a Semaphore administrator's login and "
                         "password, or set SEMAPHORE_API_TOKEN to an administrator's API token. "
                         "Nothing was changed.")
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
    return session_user(client)


def session_user(client):
    """The user of the session a password login opened.

    Semaphore accepts a password before it asks for a second factor, so the
    login is complete only once GET /user answers.
    """
    try:
        return client.call("GET", "/user")
    except ApiError as error:
        if error.status != 401:
            raise
        # TOTP_REQUIRED for an account with one-time codes; no reason when no session came back.
        cause = (f"Semaphore also wants a second factor ({error.reason}), which this script cannot enter"
                 if error.reason else "Semaphore did not accept the session it had just opened")
        raise SystemExit(f"The password was accepted, but {cause}. Create an API token for a Semaphore "
                         "administrator in the UI, set SEMAPHORE_API_TOKEN to it and run this again with "
                         "sudo --preserve-env=SEMAPHORE_API_TOKEN. Nothing was changed.") from None


def check_access(client, user, found):
    """Stop before any change unless this login may change the project's templates."""
    if user.get("admin"):
        return
    role = client.call("GET", f"{found['base']}/role") or {}
    if not (role.get("permissions") or 0) & CAN_MANAGE_PROJECT_RESOURCES:
        raise SystemExit(f"Semaphore user {user.get('username')!r} may not change the templates of project "
                         f"{found['project']['name']!r} (project role: {role.get('role') or 'none'}). Use the "
                         "login or API token of a Semaphore administrator, or of the project's owner or a "
                         "manager. Nothing was changed.")


def exactly_one(items, what, hint):
    if len(items) != 1:
        found = ", ".join(str(item["id"]) for item in items) or "none"
        raise SystemExit(f"Expected one {what}, found {len(items)} (IDs: {found}). {hint} Nothing was changed.")
    return items[0]


def resolve(client, project_name, lab_dir, project_id=None, user=None):
    """Find the seeded project and its lab folder objects by what they are, not only by name."""
    projects = client.call("GET", "/projects") or []
    matches = ([p for p in projects if p["id"] == project_id] if project_id
               else [p for p in projects if p.get("name") == project_name])
    if matches:
        hint = "Pass --project-id with the ID of the seeded one."
    elif (user or {}).get("admin"):
        # An administrator sees every project, so this one was renamed or deleted.
        hint = (f"No project has ID {project_id}; check --project-id." if project_id else
                f"No project is named {project_name!r}; if you renamed it, pass --project-id with its ID.")
    else:
        hint = ("A login that is not a Semaphore administrator sees only the projects it belongs "
                "to; use the login or API token of an administrator, or of the project's owner or a "
                "manager" + (", and check --project-id." if project_id else
                             ". If you renamed the project, pass --project-id with its ID."))
    project = exactly_one(matches, f"project named {project_name!r}", hint)
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
    templates = client.call("GET", f"{base}/templates") or []
    replaced = lab_templates(templates, REPLACED_TEMPLATES, repository["id"], inventory["id"])
    return {
        "project": project, "base": base, "repository": repository, "inventory": inventory,
        "environments": client.call("GET", f"{base}/environment") or [],
        "views": client.call("GET", f"{base}/views") or [],
        "templates": templates,
        "triggers": triggers_of(client, base, [t["id"] for t in replaced]),
    }


def plan_for(found):
    return update_plan({key: found[key] for key in ("environments", "views", "templates", "triggers")},
                       found["repository"]["id"], found["inventory"]["id"])


def read_list(client, path):
    """GET a list of objects; any other answer stops like a refused request."""
    answer = client.call("GET", path)
    if answer is None:
        return []
    if not isinstance(answer, list) or not all(isinstance(item, dict) for item in answer):
        raise SystemExit(f"GET {path} did not answer with a list")
    return answer


def triggers_of(client, base, template_ids):
    """The schedules and integrations that run each template, by template ID.

    Semaphore deletes them with their template. Its project schedule list holds
    only timed schedules, and a template's own schedule list only its commit
    checks, so both are read. A template whose triggers could not be read maps
    to {"error": reason} instead.
    """
    if not template_ids:
        return {}
    try:
        timed = read_list(client, f"{base}/schedules")
        integrations = read_list(client, f"{base}/integrations")
    except SystemExit as error:
        return {template_id: {"error": str(error)} for template_id in template_ids}
    result = {}
    for template_id in template_ids:
        try:
            commit_checks = read_list(client, f"{base}/templates/{template_id}/schedules")
        except SystemExit as error:
            result[template_id] = {"error": str(error)}
            continue
        schedules = {s["id"]: s for s in timed + commit_checks if s.get("template_id") == template_id}
        result[template_id] = {"schedules": list(schedules.values()),
                               "integrations": [i for i in integrations if i.get("template_id") == template_id]}
    return result


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


def seeded_vaults(client, base, found):
    """The vault passwords that every seeded template shares, for the templates an update adds.

    Chapter 3b's per-target sudo option adds a vault password to every template.
    Returns (vaults, note): vaults is empty when the seeded templates use none or
    differ, and note says what a person should check then.
    """
    names = set(VIEW_OF) | set(REPLACED_TEMPLATES)
    shared = set()
    for template in lab_templates(found["templates"], names, found["repository"]["id"], found["inventory"]["id"]):
        # Only GET of one template lists its vaults. A script vault has no key, and a
        # vault's name is its vault ID for ansible-playbook, so both are kept.
        vaults = client.call("GET", f"{base}/templates/{template['id']}").get("vaults") or []
        shared.add(tuple(sorted(((v.get("vault_key_id"), v.get("type") or "password", v.get("script") or "",
                                  v.get("name") or "") for v in vaults), key=repr)))
    if len(shared) == 1 and next(iter(shared)):
        vaults = [{"type": kind, **({"vault_key_id": key} if key is not None else {}),
                   **({"script": script} if script else {}), **({"name": name} if name else {})}
                  for key, kind, script, name in next(iter(shared))]
        return vaults, "The new templates use the same vault password as your seeded templates."
    if any(shared):
        return [], ("Your seeded templates use different vault passwords, so the new templates have none; "
                    "add yours under Ansible options -> Vaults if they need one.")
    return [], None


def removable(plan):
    replaced = plan["replaced"]
    return bool(replaced["templates"] or replaced["views"] or replaced["environments"])


def take_backup(client, base, found, backup_dir, prefix, extra=None):
    """Save every template as it is now, and any extra objects, root-only; returns the path."""
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Names sort by time, and two runs in one second never share one.
    stamp = time.time_ns()
    path = backup_dir / (f"{prefix}-{time.strftime('%Y%m%dT%H%M%S', time.localtime(stamp // 10**9))}"
                         f"-{stamp % 10**9:09d}.json")
    details = [client.call("GET", f"{base}/templates/{t['id']}")
               for t in client.call("GET", f"{base}/templates") or []]
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        json.dump(details if extra is None else {"templates": details, **extra}, handle, indent=2)
    return path


def remove_replaced(client, found, plan, backup_dir, say=print):
    """Delete what the plan lists as replaced, after a backup, checking each object again first.

    A template that a schedule or integration now runs is kept, because Semaphore
    would delete those with it. Returns (backup path or None, the names of what
    was removed).
    """
    for template in plan["in_use"]:
        say(f"Kept template {template['name']!r}: {why_kept(template)}")
    if not removable(plan):
        return None, []
    base = found["base"]
    replaced = plan["replaced"]
    view_ids = {v["id"] for v in replaced["views"]}
    environment_ids = {e["id"] for e in replaced["environments"]}
    triggers = triggers_of(client, base, [t["id"] for t in replaced["templates"] + plan["in_use"]])
    backup = take_backup(client, base, found, backup_dir, "semaphore-before-removal", {
        "views": [v for v in client.call("GET", f"{base}/views") or [] if v["id"] in view_ids],
        "environments": [e for e in client.call("GET", f"{base}/environment") or [] if e["id"] in environment_ids],
        # What runs the replaced templates. Their templates are kept, and these with them.
        "schedules": [s for runs in triggers.values() for s in runs.get("schedules", [])],
        "integrations": [i for runs in triggers.values() for i in runs.get("integrations", [])],
    })
    say(f"Templates, tab, variable group, schedules and integrations as they were before: {backup}")
    removed = []
    repository_id, inventory_id = found["repository"]["id"], found["inventory"]["id"]
    for template in replaced["templates"]:
        current = client.call("GET", f"{base}/templates/{template['id']}")
        if (current.get("name") != template["name"] or current.get("repository_id") != repository_id
                or current.get("inventory_id") != inventory_id):
            say(f"Kept template {template['name']!r}: it changed since the plan")
            continue
        runs = triggers_of(client, base, [template["id"]])[template["id"]]
        if triggered(runs):
            say(f"Kept template {template['name']!r}: {why_kept(dict(template, **trigger_names(runs)))}")
            continue
        client.call("DELETE", f"{base}/templates/{template['id']}")
        removed.append(f"template {template['name']!r}")
        say(f"Removed template {template['name']!r} and its task history")
    remaining = [client.call("GET", f"{base}/templates/{t['id']}")
                 for t in client.call("GET", f"{base}/templates") or []]
    for view in replaced["views"]:
        if any(t.get("view_id") == view["id"] for t in remaining):
            say(f"Kept tab {view['title']!r}: other templates are on it")
            continue
        client.call("DELETE", f"{base}/views/{view['id']}")
        removed.append(f"tab {view['title']!r}")
        say(f"Removed tab {view['title']!r}")
    current = {e["id"]: e for e in client.call("GET", f"{base}/environment") or []}
    for environment in replaced["environments"]:
        if any(environment["id"] in environments_of(t) for t in remaining):
            say(f"Kept variable group {environment['name']!r}: other templates use it")
            continue
        if environment["id"] not in current or edited(current[environment["id"]]):
            say(f"Kept variable group {environment['name']!r}: it changed since the plan")
            continue
        client.call("DELETE", f"{base}/environment/{environment['id']}")
        removed.append(f"variable group {environment['name']!r}")
        say(f"Removed variable group {environment['name']!r}")
    return backup, removed


def apply_update(client, found, plan, backup_dir, say=print):
    """Add what the plan lists. Returns the path of the template backup, if one was taken.

    It removes nothing; remove_replaced() does that, once the lab folder holds
    the playbooks the new templates run.
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
    # Read the vault passwords for the new templates first, so a failure changes nothing.
    vaults, note = seeded_vaults(client, base, found) if plan["templates"] else ([], None)
    if note:
        say(note)
    backup = None
    if plan["tabs"]:
        # Semaphore rewrites a template's variable-group links when it saves one; keep
        # every template as it was, root-only, before changing any of them.
        backup = take_backup(client, base, found, backup_dir, "semaphore-templates")
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
            client.call("POST", f"{base}/templates", template_payload(project_id, ids, lesson, vaults))
    for tab in plan["tabs"]:
        path = f"{base}/templates/{tab['id']}"
        before = client.call("GET", path)
        if before.get("view_id"):
            say(f"Kept the tab you gave {tab['name']!r} meanwhile")
            continue
        save_verified(client, path, before, dict(before, view_id=ids["views"][VIEW_OF[tab["name"]]]), backup_dir)
    return backup


def update(client, args, user):
    """--update for seed-semaphore.py itself; update-controller.py calls the parts directly."""
    found = resolve(client, args.project_name, args.lab_dir, getattr(args, "project_id", None), user)
    check_access(client, user, found)
    plan = plan_for(found)
    result = {"project": {"name": found["project"]["name"], "id": found["project"]["id"]},
              "planned" if args.plan else "done": plan}
    if not args.plan:
        notes = []
        backup = apply_update(client, found, plan, BACKUP_DIR, say=notes.append)
        if backup:
            result["template_backup"] = str(backup)
        if args.remove_replaced:
            removal_backup, removed = remove_replaced(client, found, plan, BACKUP_DIR, say=notes.append)
            result["removed"] = removed
            if removal_backup:
                result["removal_backup"] = str(removal_backup)
        result["notes"] = [note for note in notes if not note.startswith(("Templates", "Removed"))]
    print(json.dumps(result, indent=2, ensure_ascii=False))


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
                             "including the old templates' task history; a template that a schedule "
                             "or integration runs is kept")
    args = parser.parse_args()

    if args.update:
        if not MARKER.exists():
            raise SystemExit("This controller was not seeded by the installer; there is no project to update")
        client = Client(API, os.environ.get("SEMAPHORE_API_TOKEN") or None)
        wait_ready(client)
        user = log_in(client, args.admin_login, ask=True)
        update(client, args, user)
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

    client = Client(API, os.environ.get("SEMAPHORE_API_TOKEN") or None)
    wait_ready(client)
    user = log_in(client, args.admin_login, ask=True)
    if not user.get("admin"):
        raise SystemExit(f"Semaphore user {user.get('username')!r} is not an administrator; seeding needs "
                         "the login or API token of one. Nothing was changed.")

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
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
