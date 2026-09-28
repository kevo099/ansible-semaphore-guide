#!/usr/bin/env python3
"""Bring a controller made by either installer up to this copy of the guide.

Run it through scripts/update-controller.sh, as root. The default is a read-only
plan; --apply makes the changes. See docs/03-controller.md.
"""

import argparse
import grp
import importlib.util
import os
from pathlib import Path
import pwd
import secrets
import shutil
import stat
import subprocess
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MARKER = Path("/etc/semaphore/.practice-project-seeded")
# Commits whose files are the guide's own, as the installer or an update left them.
BASE_MESSAGES = ("^Seed the local lab folder from the guide$", "^Update the guide's files to ")


def load_seeder():
    spec = importlib.util.spec_from_file_location("seed_semaphore", HERE / "seed-semaphore.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guide_files(repo=REPO):
    """The files the installers copy into the lab folder, relative to it."""
    files = [str(p.relative_to(repo)) for p in (repo / "playbooks").rglob("*") if p.is_file()]
    return sorted(files + ["ansible.cfg", "scripts/summarize_xccdf.py"])


def classify(lab, base, new):
    """Three-way decision for one guide file: lab and base are None when absent.

    base is the file as the installer or the last update wrote it. A file only the
    guide changed is updated, a file only you changed is kept, and a file both
    changed is a conflict.
    """
    if lab == new:
        return "current"
    if lab is None:
        if base is None:
            return "add"
        return "removed by you" if base == new else "conflict"
    if base is not None and lab == base:
        return "update"
    if base is not None and new == base:
        return "yours"
    return "conflict"


class Unsafe(Exception):
    """A path in the lab folder is a link or the wrong kind of file."""


class LabFolder:
    """Reads and writes below one folder without ever following a symbolic link."""

    def __init__(self, root, uid, gid, git_prefix=()):
        self.root = Path(root)
        self.uid, self.gid = uid, gid
        self.git_prefix = list(git_prefix)

    def _walk(self, parts, create=False):
        """Open each folder in parts below the root; None if one is missing and not created."""
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.root, flags)
        for part in parts:
            try:
                try:
                    child = os.open(part, flags, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        os.close(fd)
                        return None
                    os.mkdir(part, 0o700, dir_fd=fd)
                    child = os.open(part, flags, dir_fd=fd)
                    try:
                        os.fchown(child, self.uid, self.gid)
                        os.fchmod(child, 0o2750)
                    except BaseException:
                        os.close(child)
                        raise
            except FileNotFoundError:
                os.close(fd)
                raise
            except OSError as error:
                os.close(fd)
                raise Unsafe(f"{'/'.join(parts)} is a link or a file where a folder belongs") from error
            except BaseException:
                os.close(fd)
                raise
            os.close(fd)
            fd = child
        return fd

    def read(self, relative):
        """Bytes of a regular file, None if absent; Unsafe for a link or anything else."""
        *folders, leaf = relative.split("/")
        fd = self._walk(folders)
        if fd is None:
            return None
        try:
            try:
                info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
            if not stat.S_ISREG(info.st_mode):
                raise Unsafe(f"{relative} is not a regular file")
            handle = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(handle, "rb") as source:
                return source.read()
        finally:
            os.close(fd)

    def folder_state(self, relative):
        """'folder', 'missing', or Unsafe."""
        fd = self._walk(relative.split("/"))
        if fd is None:
            return "missing"
        os.close(fd)
        return "folder"

    def write(self, relative, data):
        """Replace one file atomically, owned by the folder's editor and the service group."""
        *folders, leaf = relative.split("/")
        fd = self._walk(folders, create=True)
        temporary = f".{leaf}.{secrets.token_hex(8)}.update"
        try:
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(handle, "wb") as target:
                    target.write(data)
                    target.flush()
                    os.fchown(target.fileno(), self.uid, self.gid)
                    os.fchmod(target.fileno(), 0o640)
                    os.fsync(target.fileno())
                os.rename(temporary, leaf, src_dir_fd=fd, dst_dir_fd=fd)
            except BaseException:
                try:
                    os.unlink(temporary, dir_fd=fd)
                except FileNotFoundError:
                    pass
                raise
        finally:
            os.close(fd)

    def make_folder(self, relative):
        fd = self._walk(relative.split("/"), create=True)
        os.close(fd)

    def git(self, *arguments, check=True):
        result = subprocess.run(self.git_prefix + ["git", "-C", str(self.root), *arguments],
                                capture_output=True)
        if check and result.returncode != 0:
            raise SystemExit(f"git {' '.join(arguments[:2])} failed in {self.root}: "
                             f"{result.stderr.decode(errors='replace').strip()}")
        return result

    def base_commit(self):
        greps = [f"--grep={pattern}" for pattern in BASE_MESSAGES]
        out = self.git("log", "-1", "--format=%H", *greps).stdout.decode().strip()
        return out or None

    def committed(self, commit, relative):
        result = self.git("show", f"{commit}:{relative}", check=False)
        return result.stdout if result.returncode == 0 else None


def lab_plan(lab, repo, files, replace_edited):
    """Everything the file part would do, and every reason it must not."""
    plan = {name: [] for name in ("add", "update", "yours", "removed by you", "conflict", "current")}
    problems = []
    for folder in ("content",):
        try:
            lab.folder_state(folder)
        except Unsafe as error:
            problems.append(str(error))
    if lab.git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
        problems.append("the lab folder's Git history has no commits")
        return plan, problems, None
    if lab.git("diff", "--cached", "--quiet", check=False).returncode != 0:
        problems.append("the lab folder's Git index has staged changes; commit or unstage them first")
    status = lab.git("status", "--porcelain=v1", "-z", "--ignored", "--untracked-files=all", "--",
                     *files).stdout.decode(errors="replace")
    for entry in filter(None, status.split("\0")):
        problems.append(f"uncommitted change to a guide file: {entry} (commit or discard it; after an "
                        "interrupted update, commit the files it wrote)")
    base = lab.base_commit()
    for relative in files:
        try:
            current = lab.read(relative)
        except Unsafe as error:
            problems.append(str(error))
            continue
        new = (repo / relative).read_bytes()
        decision = classify(current, lab.committed(base, relative) if base else None, new)
        if decision == "conflict" and replace_edited:
            decision = "update"
        plan[decision].append(relative)
    if plan["conflict"]:
        problems.append("guide files that both you and this release changed: " + ", ".join(plan["conflict"])
                        + ". Compare them with the new copy; --replace-edited replaces yours, and Git keeps them")
    return plan, problems, base


def show(title, items):
    print(f"  {title}: {len(items)}")
    for item in items:
        print(f"    {item}")


def run_check(command):
    return subprocess.run(command, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="show what would change (the default)")
    mode.add_argument("--apply", action="store_true", help="make the changes")
    parser.add_argument("--lab-dir", default="/opt/ansible-lab")
    parser.add_argument("--replace-edited", action="store_true",
                        help="replace guide files that both you and this release changed")
    parser.add_argument("--project-id", type=int, help="the seeded project's ID, when project names repeat")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise SystemExit("Run it with sudo on the controller.")
    if not MARKER.exists():
        raise SystemExit("This controller was not set up by an installer that seeds Semaphore; "
                         "there is nothing to update.")
    root = Path(os.path.realpath(args.lab_dir))
    if not (root / ".git").is_dir():
        raise SystemExit(f"No lab folder with Git history at {root}; pass --lab-dir.")
    if run_check(["systemctl", "is-active", "--quiet", "semaphore"]).returncode != 0:
        raise SystemExit("semaphore.service is not running; start it first.")
    owner = pwd.getpwuid(os.stat(root).st_uid)
    if owner.pw_uid == 0:
        raise SystemExit(f"{root} belongs to root; the installer gives it to an administrator.")
    lab = LabFolder(root, owner.pw_uid, grp.getgrnam("semaphore").gr_gid,
                    ["runuser", "-u", owner.pw_name, "--"])
    version = run_check(["git", "-c", f"safe.directory={REPO}", "-C", str(REPO), "describe", "--tags",
                         "--always"]).stdout.strip() or "this copy"
    files = guide_files()

    plan, problems, base = lab_plan(lab, REPO, files, args.replace_edited)
    print(f"Guide {version} -> lab folder {root} (owned by {owner.pw_name})")
    show("Files to add", plan["add"])
    show("Files to update (only the guide changed them)", plan["update"])
    show("Your edits, kept (the guide did not change these files)", plan["yours"])
    show("Guide files you removed, left removed", plan["removed by you"])
    show("Files that both changed", plan["conflict"])
    print(f"  Guide files already current: {len(plan['current'])}")
    try:
        needs_content = lab.folder_state("content") == "missing"
    except Unsafe:
        needs_content = False
    if needs_content:
        print("  content/ will be created for SCAP files you supply")
    if not base:
        print("  No earlier guide commit was found, so every differing file counts as changed by both.")
    for problem in problems:
        print(f"  Problem: {problem}")
    if args.apply and problems:
        raise SystemExit("Nothing was changed. Resolve the problems above and run again.")

    seeder = load_seeder()
    client = seeder.Client(seeder.API, os.environ.get("SEMAPHORE_API_TOKEN") or None)
    seeder.wait_ready(client)
    seeder.log_in(client, "admin", ask=True)
    found = seeder.resolve(client, "Ansible Practice", str(root), args.project_id)
    semaphore_plan = seeder.plan_for(found)
    print(f"Semaphore project {found['project']['name']!r} (ID {found['project']['id']})")
    show("Variable groups to add", semaphore_plan["environments"])
    show("Template tabs to add", semaphore_plan["views"])
    show("Templates to add", semaphore_plan["templates"])
    show("Templates to put on their tab", [t["name"] for t in semaphore_plan["tabs"]])
    if semaphore_plan["without_variable_group"]:
        show("Seeded templates with no variable group (check them in the UI)",
             semaphore_plan["without_variable_group"])
    for item in semaphore_plan["ambiguous"]:
        print(f"  Problem: several objects are named {item}")
    if not args.apply:
        print("Plan only. Run again with --apply to make these changes.")
        return 0
    if semaphore_plan["ambiguous"]:
        raise SystemExit("Nothing was changed. Rename or remove the duplicates, then run again.")

    backup = seeder.apply_update(client, found, semaphore_plan, Path("/root/ansible-lab-update"))
    if backup:
        print(f"Templates as they were before: {backup}")

    written = plan["add"] + plan["update"]
    for relative in written:
        lab.write(relative, (REPO / relative).read_bytes())
    lab.make_folder("content")
    selinux = shutil.which("selinuxenabled")
    if selinux and run_check([selinux]).returncode == 0:
        subprocess.run(["restorecon", "-RF", str(root)], check=True)
    for relative in written:
        if run_check(["runuser", "-u", "semaphore", "--", "test", "-r", str(root / relative)]).returncode:
            raise SystemExit(f"The semaphore account cannot read {root / relative}.")
    if written:
        name = lab.git("config", "user.name", check=False).stdout.strip()
        identity = [] if name else ["-c", "user.name=ansible-practice", "-c", "user.email=ansible-practice@example.test"]
        lab.git("add", "--", *written)
        result = lab.git(*identity, "commit", "-q", "-m", f"Update the guide's files to {version}", "--", *written,
                         check=False)
        if result.returncode != 0:
            raise SystemExit("The files were written but not committed: "
                             f"{result.stderr.decode(errors='replace').strip()}\nCommit them in {root} with: "
                             f"git commit -m \"Update the guide's files to {version}\" -- " + " ".join(written))
        print(f"Committed {len(written)} file(s) in {root}; git revert HEAD there undoes them.")

    check = run_check(["python3.12", str(HERE / "check-controller.py")])
    if check.returncode != 0:
        raise SystemExit("The readiness check failed; run sudo python3.12 scripts/check-controller.py to see why.")
    print(f"Updated to {version}. The readiness check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
