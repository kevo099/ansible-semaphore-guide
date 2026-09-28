#!/usr/bin/env python3
"""Bring a controller made by either installer up to this copy of the guide.

Run it through scripts/update-controller.sh, as root. The default is a read-only
plan; --apply makes the changes. See docs/03-controller.md.
"""

import argparse
import fcntl
import grp
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import stat
import subprocess
import sys


# Run as root from an administrator's copy of the guide: leave no root-owned bytecode in it.
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MARKER = Path("/etc/semaphore/.practice-project-seeded")
# The guide's own version of each file, recorded by every update as SHA-256 hashes.
# Before the first update, the installer's first commit holds the guide's files.
MANIFEST = ".guide-files.json"
SEED_MESSAGE = "^Seed the local lab folder from the guide$"
FALLBACK_IDENTITY = ["-c", "user.name=ansible-practice", "-c", "user.email=ansible-practice@example.test"]
DECISIONS = ("add", "update", "remove", "yours", "removed by you", "conflict", "current")


def load_seeder():
    spec = importlib.util.spec_from_file_location("seed_semaphore", HERE / "seed-semaphore.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_guide_path(relative):
    return relative.startswith("playbooks/") or relative in ("ansible.cfg", "scripts/summarize_xccdf.py")


def guide_files(repo=REPO):
    """The files the installers copy into the lab folder, relative to it."""
    files = [str(p.relative_to(repo)) for p in (repo / "playbooks").rglob("*") if p.is_file()]
    return sorted(files + ["ansible.cfg", "scripts/summarize_xccdf.py"])


def digest(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def classify(lab, base, new):
    """Three-way decision for one path, from hashes; None means absent.

    base is the guide's version the installer or the last update put there, and
    None when the path was not the guide's. new is None when this release removes
    the file. A file only the guide changed is updated or removed, a file only you
    changed is kept, and anything both changed is a conflict. A file of yours at a
    path the release now uses stays yours until you choose, even if it matches.
    """
    if new is None:
        if lab is None:
            return "current"
        return "remove" if lab == base else "conflict"
    if base is None:
        return "add" if lab is None else "conflict"
    if lab == new:
        return "current"
    if lab is None:
        return "removed by you" if base == new else "conflict"
    if lab == base:
        return "update"
    if new == base:
        return "yours"
    return "conflict"


class Unsafe(Exception):
    """A path in the lab folder is a link, the wrong kind of file, or changed meanwhile."""


class LabFolder:
    """Reads and writes below one folder without ever following a symbolic link."""

    FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def __init__(self, root, uid, gid, git_prefix=()):
        self.root = Path(root)
        self.uid, self.gid = uid, gid
        self.git_prefix = list(git_prefix)
        # Open every component from / without following a link, and keep that
        # folder for the whole run, so a path swapped later cannot redirect writes.
        fd = os.open("/", self.FLAGS)
        try:
            for part in self.root.parts[1:]:
                child = os.open(part, self.FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
        except OSError:
            os.close(fd)
            raise Unsafe(f"{self.root} is not a real folder (a link somewhere in its path?)") from None
        self.root_fd = fd
        info = os.fstat(fd)
        self.identity = (info.st_dev, info.st_ino)

    def close(self):
        os.close(self.root_fd)

    def lock(self):
        try:
            fcntl.flock(self.root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another update of this lab folder is running.") from None

    def same_folder(self):
        """Whether the path still names the folder that was opened, for tools that take a path."""
        try:
            info = os.stat(self.root)
        except OSError:
            return False
        return (info.st_dev, info.st_ino) == self.identity

    def _walk(self, parts, create=False):
        """Open each folder in parts below the root; None if one is missing and not created."""
        fd = os.dup(self.root_fd)
        for part in parts:
            try:
                try:
                    child = os.open(part, self.FLAGS, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        os.close(fd)
                        return None
                    os.mkdir(part, 0o700, dir_fd=fd)
                    child = os.open(part, self.FLAGS, dir_fd=fd)
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

    @staticmethod
    def _read_at(fd, leaf, relative):
        try:
            info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode):
            raise Unsafe(f"{relative} is not a regular file")
        handle = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(handle, "rb") as source:
            return source.read()

    def read(self, relative):
        """Bytes of a regular file, None if absent; Unsafe for a link or anything else."""
        *folders, leaf = relative.split("/")
        fd = self._walk(folders)
        if fd is None:
            return None
        try:
            return self._read_at(fd, leaf, relative)
        finally:
            os.close(fd)

    def folder_state(self, relative):
        """'folder', 'missing', or Unsafe."""
        fd = self._walk(relative.split("/"))
        if fd is None:
            return "missing"
        os.close(fd)
        return "folder"

    def write(self, relative, data, expected):
        """Replace one file atomically if it still has the expected hash (None: absent)."""
        *folders, leaf = relative.split("/")
        fd = self._walk(folders, create=True)
        temporary = f".{leaf}.{secrets.token_hex(8)}.update"
        try:
            if digest(self._read_at(fd, leaf, relative)) != expected:
                raise Unsafe(f"{relative} changed after the plan was made")
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(handle, "wb") as target:
                    target.write(data)
                    target.flush()
                    os.fchown(target.fileno(), self.uid, self.gid)
                    os.fchmod(target.fileno(), 0o640)
                    os.fsync(target.fileno())
                if expected is None:
                    # A new file must not replace one that appeared meanwhile.
                    try:
                        os.link(temporary, leaf, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                    except FileExistsError:
                        raise Unsafe(f"{relative} appeared after the plan was made") from None
                    os.unlink(temporary, dir_fd=fd)
                else:
                    os.rename(temporary, leaf, src_dir_fd=fd, dst_dir_fd=fd)
            except BaseException:
                try:
                    os.unlink(temporary, dir_fd=fd)
                except FileNotFoundError:
                    pass
                raise
        finally:
            os.close(fd)

    def remove(self, relative, expected):
        *folders, leaf = relative.split("/")
        fd = self._walk(folders)
        if fd is None:
            return
        try:
            if digest(self._read_at(fd, leaf, relative)) != expected:
                raise Unsafe(f"{relative} changed after the plan was made")
            os.unlink(leaf, dir_fd=fd)
        finally:
            os.close(fd)

    def make_folder(self, relative):
        fd = self._walk(relative.split("/"), create=True)
        os.close(fd)

    def git(self, *arguments, check=True):
        if not self.same_folder():
            raise SystemExit(f"{self.root} no longer names the folder the update opened; stopped.")
        result = subprocess.run(self.git_prefix + ["git", "-C", str(self.root), *arguments],
                                capture_output=True)
        if check and result.returncode != 0:
            raise SystemExit(f"git {' '.join(arguments[:2])} failed in {self.root}: "
                             f"{result.stderr.decode(errors='replace').strip()}")
        return result

    def seed_commit(self):
        out = self.git("log", "--reverse", "--format=%H", f"--grep={SEED_MESSAGE}").stdout.decode().split()
        return out[0] if out else None

    def committed(self, commit, relative):
        result = self.git("show", f"{commit}:{relative}", check=False)
        return result.stdout if result.returncode == 0 else None


def base_hashes(lab):
    """The guide's own hash of each of its files as last installed, and where that came from."""
    recorded = lab.read(MANIFEST)
    if recorded is not None:
        try:
            files = json.loads(recorded)["files"]
            if not all(is_guide_path(k) and re.fullmatch(r"[0-9a-f]{64}", v) for k, v in files.items()):
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise Unsafe(f"{MANIFEST} is not a record of guide file hashes; restore it with git") from None
        return files, MANIFEST
    if lab.git("log", "-1", "--format=%H", "--", MANIFEST).stdout.strip():
        raise Unsafe(f"{MANIFEST}, the record of the guide's versions, was removed. Restore it with: git "
                     f"checkout \"$(git rev-list -n 1 HEAD -- {MANIFEST})^\" -- {MANIFEST}")
    seed = lab.seed_commit()
    if not seed:
        return {}, None
    listed = lab.git("ls-tree", "-r", "-z", "--name-only", seed).stdout.decode(errors="surrogateescape")
    return ({p: digest(lab.committed(seed, p)) for p in filter(None, listed.split("\0")) if is_guide_path(p)},
            "the installer's commit")


def lab_plan(lab, repo, files, replace_edited):
    """Everything the file part would do, and every reason it must not."""
    plan = {name: [] for name in DECISIONS}
    expected, problems, source = {}, [], None
    try:
        lab.folder_state("content")
    except Unsafe as error:
        problems.append(str(error))
    if lab.git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
        problems.append("the lab folder's Git history has no commits")
        return plan, expected, problems, source
    if lab.git("diff", "--cached", "--quiet", check=False).returncode != 0:
        problems.append("the lab folder's Git index has staged changes; commit or unstage them first")
    try:
        base, source = base_hashes(lab)
    except Unsafe as error:
        problems.append(str(error))
        return plan, expected, problems, source
    paths = sorted(set(files) | set(base))
    status = lab.git("status", "--porcelain=v1", "-z", "--ignored", "--untracked-files=all", "--",
                     *paths, MANIFEST).stdout.decode(errors="replace")
    for entry in filter(None, status.split("\0")):
        problems.append(f"uncommitted change to a guide file: {entry} (commit or discard it; after an "
                        "interrupted update, commit the files it wrote)")
    for relative in paths:
        try:
            current = digest(lab.read(relative))
        except Unsafe as error:
            problems.append(str(error))
            continue
        expected[relative] = current
        new = digest((repo / relative).read_bytes()) if relative in files else None
        decision = classify(current, base.get(relative), new)
        if decision == "conflict" and replace_edited:
            decision = "update" if new is not None else "remove"
        plan[decision].append(relative)
    if plan["conflict"]:
        problems.append("files that both you and this release changed or claim: " + ", ".join(plan["conflict"])
                        + ". Compare them with the new copy; --replace-edited takes the release's version, "
                        "and Git keeps yours")
    return plan, expected, problems, source


def manifest_for(repo, files, version):
    return (json.dumps({"guide": version, "files": {f: digest((repo / f).read_bytes()) for f in files}},
                       indent=2, sort_keys=True) + "\n").encode()


def show(title, items):
    print(f"  {title}: {len(items)}")
    for item in items:
        print(f"    {item}")


def run_check(command):
    return subprocess.run(command, capture_output=True, text=True)


def commit_identity(lab):
    """Git options that give a usable author and committer, or None if none does."""
    for options in ([], FALLBACK_IDENTITY):
        if all(lab.git(*options, "var", name, check=False).returncode == 0
               for name in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT")):
            return options
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="show what would change (the default)")
    mode.add_argument("--apply", action="store_true", help="make the changes")
    parser.add_argument("--lab-dir", default="/opt/ansible-lab")
    parser.add_argument("--replace-edited", action="store_true",
                        help="take the release's version of files that both you and it changed")
    parser.add_argument("--project-id", type=int, help="the seeded project's ID, when project names repeat")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise SystemExit("Run it with sudo on the controller.")
    if not MARKER.exists():
        raise SystemExit("This controller was not set up by an installer that seeds Semaphore; "
                         "there is nothing to update.")
    root = Path(os.path.realpath(args.lab_dir))
    if run_check(["systemctl", "is-active", "--quiet", "semaphore"]).returncode != 0:
        raise SystemExit("semaphore.service is not running; start it first.")
    owner = pwd.getpwuid(os.stat(root).st_uid)
    if owner.pw_uid == 0:
        raise SystemExit(f"{root} belongs to root; the installer gives it to an administrator.")
    try:
        lab = LabFolder(root, owner.pw_uid, grp.getgrnam("semaphore").gr_gid,
                        ["runuser", "-u", owner.pw_name, "--"])
    except Unsafe as error:
        raise SystemExit(str(error)) from None
    lab.lock()
    if not (root / ".git").is_dir():
        raise SystemExit(f"No lab folder with Git history at {root}; pass --lab-dir.")
    version = run_check(["git", "-c", f"safe.directory={REPO}", "-C", str(REPO), "describe", "--tags",
                         "--always"]).stdout.strip() or "this copy"
    files = guide_files()

    plan, expected, problems, source = lab_plan(lab, REPO, files, args.replace_edited)
    identity = commit_identity(lab)
    if identity is None:
        problems.append(f"Git has no usable author identity for {owner.pw_name}; set user.name and user.email")
    print(f"Guide {version} -> lab folder {root} (owned by {owner.pw_name})")
    show("Files to add", plan["add"])
    show("Files to update (only the guide changed them)", plan["update"])
    show("Files to remove (this release dropped them; you had not changed them)", plan["remove"])
    show("Your edits, kept (the guide did not change these files)", plan["yours"])
    show("Guide files you removed, left removed", plan["removed by you"])
    show("Files that both you and this release changed or claim", plan["conflict"])
    print(f"  Guide files already current: {len(plan['current'])}")
    try:
        needs_content = lab.folder_state("content") == "missing"
    except Unsafe:
        needs_content = False
    if needs_content:
        print("  content/ will be created for SCAP files you supply")
    if source:
        print(f"  The guide's earlier versions come from {source}.")
    else:
        print("  No record of the guide's earlier files was found, so every differing file counts as changed by both.")
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
    if semaphore_plan["repair"]:
        show("Seeded templates without a variable group, to repair from a backup",
             [t["name"] for t in semaphore_plan["repair"]])
    if semaphore_plan["duplicates"]:
        show("Seeded template names used more than once, left as they are", semaphore_plan["duplicates"])
    for item in semaphore_plan["ambiguous"]:
        print(f"  Problem: several objects are named {item}")
    if not args.apply:
        print("Plan only. Run again with --apply to make these changes.")
        return 0
    if semaphore_plan["ambiguous"]:
        raise SystemExit("Nothing was changed. Rename or remove the duplicates, then run again.")

    seeder.apply_update(client, found, semaphore_plan, Path("/root/ansible-lab-update"))

    # The Semaphore part can take a while (and a login prompt); make sure the folder
    # is exactly as planned before touching it.
    again, expected_again, problems, _source = lab_plan(lab, REPO, files, args.replace_edited)
    if problems or again != plan or expected_again != expected:
        raise SystemExit("The lab folder changed while Semaphore was being updated. Semaphore is updated; "
                         "nothing in the folder was changed. Run the update again.")
    changed = []
    for relative in plan["add"] + plan["update"]:
        lab.write(relative, (REPO / relative).read_bytes(), expected[relative])
        changed.append(relative)
    for relative in plan["remove"]:
        lab.remove(relative, expected[relative])
        changed.append(relative)
    manifest = manifest_for(REPO, files, version)
    current_manifest = lab.read(MANIFEST)
    if current_manifest != manifest:
        lab.write(MANIFEST, manifest, digest(current_manifest))
        changed.append(MANIFEST)
    lab.make_folder("content")
    selinux = shutil.which("selinuxenabled")
    if selinux and run_check([selinux]).returncode == 0 and lab.same_folder():
        subprocess.run(["restorecon", "-RF", str(root)], check=True)
    for relative in plan["add"] + plan["update"]:
        if run_check(["runuser", "-u", "semaphore", "--", "test", "-r", str(root / relative)]).returncode:
            raise SystemExit(f"The semaphore account cannot read {root / relative}.")
    if changed:
        lab.git("add", "--", *changed)
        result = lab.git(*identity, "commit", "-q", "-m", f"Update the guide's files to {version}", "--",
                         *changed, check=False)
        if result.returncode != 0:
            raise SystemExit("The files were written but not committed: "
                             f"{result.stderr.decode(errors='replace').strip()}\nCommit them in {root} with: "
                             f"git commit -m \"Update the guide's files to {version}\" -- " + " ".join(changed))
        print(f"Committed {len(changed)} file(s) in {root}; git revert HEAD there undoes them.")

    check = run_check(["python3.12", str(HERE / "check-controller.py")])
    if check.returncode != 0:
        raise SystemExit("The readiness check failed; run sudo python3.12 scripts/check-controller.py to see why.")
    print(f"Updated to {version}. The readiness check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
