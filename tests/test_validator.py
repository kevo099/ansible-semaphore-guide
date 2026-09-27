"""Offline checks that the repository validator's publication rules catch what they claim.

Samples that would trip the validator are assembled from parts at runtime, so this
file passes the validator itself.
"""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate", ROOT / "scripts" / "validate.py")
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)

ADDRESS = ".".join(["192", "0", "2", "10"])
ADDRESS_RULE = "literal non-loopback address; use documentation hostnames"
HOME = "/home/"
OWNER = "kevo099"


class PublicationBoundaryTests(unittest.TestCase):
    def rules(self, text):
        validate.errors.clear()
        validate.publication_boundary(ROOT / "docs" / "example.md", text)
        found = [error.split(": ", 1)[1] for error in validate.errors]
        validate.errors.clear()
        return found

    def test_address_is_rejected_wherever_it_appears_in_prose(self):
        for text in (f"Reach it at {ADDRESS}.", f"Reach {ADDRESS}, then log in.",
                     f"({ADDRESS})", f"{ADDRESS}:3000", f"ssh admin@{ADDRESS}"):
            with self.subTest(text=text):
                self.assertIn(ADDRESS_RULE, self.rules(text))

    def test_loopback_and_version_strings_are_accepted(self):
        self.assertEqual(self.rules("Use 127.0.0.1. Version 1.2.3.4.5 is not an address."), [])
        self.assertEqual(self.rules("Semaphore 2.19.12 and ansible-core 2.20.8."), [])

    def test_personal_home_directory_is_rejected_without_a_trailing_slash(self):
        for text in (f"cd {HOME}someone", f"`{HOME}someone`", f"({HOME}someone)", f"{HOME}someone/lab"):
            with self.subTest(text=text):
                self.assertIn("personal workspace path", self.rules(text))

    def test_service_account_home_and_placeholders_are_accepted(self):
        self.assertEqual(self.rules(f"{HOME}svc_ansible/.ssh and {HOME}<user>/"), [])
        self.assertEqual(self.rules(f"Keys live in {HOME}svc_ansible."), [])
        self.assertIn("personal workspace path", self.rules(f"{HOME}svc_ansible-old/.ssh"))

    def test_uppercase_identifier_is_rejected(self):
        for parts in (["5F3C2A10", "1B2C", "4D5E", "8F90", "ABCDEF123456"],
                      ["5f3c2a10", "1b2c", "4d5e", "8f90", "abcdef123456"]):
            with self.subTest(parts=parts):
                self.assertIn("machine/account identifier", self.rules("-".join(parts)))

    def test_every_private_key_header_is_rejected(self):
        for kind in ("", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED "):
            with self.subTest(kind=kind):
                header = "-----BEGIN " + kind + "PRIVATE" + " KEY-----"
                self.assertIn("private key material", self.rules(header))

    def test_other_owner_repositories_are_rejected_in_any_link_form(self):
        for text in (f"https://github.com/{OWNER}/other-lab", f"git@github.com:{OWNER}/other-lab.git",
                     f"https://github.com/{OWNER.capitalize()}/other-lab",
                     f"https://raw.githubusercontent.com/{OWNER}/other-lab/main/x",
                     f"https://github.com/{OWNER}/ansible-semaphore-guide-fork"):
            with self.subTest(text=text):
                self.assertIn("unreviewed owner repository link", self.rules(text))

    def test_this_repository_is_accepted_in_any_link_form(self):
        for text in (f"See https://github.com/{OWNER}/ansible-semaphore-guide.",
                     f"https://github.com/{OWNER}/ansible-semaphore-guide, then",
                     f"git clone https://github.com/{OWNER}/ansible-semaphore-guide.git",
                     f"git@github.com:{OWNER}/ansible-semaphore-guide.git",
                     f"https://github.com/{OWNER}/ansible-semaphore-guide/blob/main/README.md",
                     "https://github.com/semaphoreui/semaphore/releases/tag/v2.19.12"):
            with self.subTest(text=text):
                self.assertEqual(self.rules(text), [])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class SourceDiscoveryTests(unittest.TestCase):
    def git(self, cwd, *args):
        subprocess.run(["git", "-c", "user.name=Lab", "-c", "user.email=lab@example.test", *args],
                       cwd=cwd, check=True, capture_output=True)

    def test_clone_and_linked_worktree_both_honor_gitignore(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "clone"
            clone.mkdir()
            self.git(clone, "init", "-q", "-b", "main")
            (clone / ".gitignore").write_text("inventories/*\n")
            (clone / "README.md").write_text("guide\n")
            self.git(clone, "add", ".")
            self.git(clone, "commit", "-q", "-m", "start")
            worktree = Path(directory) / "worktree"
            self.git(clone, "worktree", "add", "-q", str(worktree))
            for root in (clone, worktree):
                with self.subTest(root=root.name):
                    (root / "inventories").mkdir(exist_ok=True)
                    (root / "inventories" / "lab.ini").write_text("private\n")
                    names = {path.relative_to(root).as_posix() for path in validate.source_files(root)}
                    self.assertEqual(names, {".gitignore", "README.md"})
