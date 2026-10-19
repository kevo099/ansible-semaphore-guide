"""Offline checks that the repository validator catches what it claims.

Samples that would trip the validator are assembled from parts at runtime, so this
file passes the validator itself.
"""

import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate", ROOT / "scripts" / "validate.py")
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)

ADDRESS = ".".join(["192", "0", "2", "10"])
ADDRESS_RULE = "literal non-loopback address; use documentation hostnames"
HOME = "/home/"
OWNER = "kevo099"
AT = "@"
CLOUD_INIT = ROOT / "examples" / "onboard" / "cloud-init.yaml"


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

    def test_azure_keys_signatures_and_entra_secrets_are_rejected(self):
        key = "Ab1+/" * 10
        for text, label in (
                ("DefaultEndpointsProtocol=https;AccountName=lab;Account" + "Key=" + key, "Azure account key"),
                ("Endpoint=sb://lab.servicebus.windows.net/;SharedAccess" + "Key=" + key, "Azure account key"),
                ("https://lab.blob.core.windows.net/c/b?sv=2022-11-02&sp=r&s" + "ig=" + "aB3%2B" * 5,
                 "Azure shared access signature"),
                ("BlobEndpoint=https://lab.blob.core.windows.net/;SharedAccess" + "Signature=sv=2022-11-02&ss=b&sp=r",
                 "Azure shared access signature"),
                ("client secret abc8" + "Q~" + "a1B2c3D4e5" * 3 + "f6g7", "Microsoft Entra client secret")):
            with self.subTest(label=label, text=text[:30]):
                self.assertIn(label, self.rules(text))

    def test_azure_placeholders_and_short_values_are_accepted(self):
        self.assertEqual(self.rules("AccountKey=REPLACE_WITH_KEY and SharedAccessSignature=REPLACE_WITH_SAS"), [])
        self.assertEqual(self.rules("https://example.test/page?sig=abc"), [])

    def test_email_addresses_are_rejected(self):
        for text in (f"user: someone{AT}contoso.com", f"Signed in as Some.One{AT}Contoso.COM.",
                     f"12345+someone{AT}users.noreply.github.com", f"<someone{AT}mail.example.co.uk>"):
            with self.subTest(text=text):
                self.assertIn("personal e-mail address", self.rules(text))

    def test_example_domains_git_remotes_units_and_ssh_algorithms_are_not_addresses(self):
        for text in ("admin@example.test, oidc-practice@idp.example.test, me@example.com, lab@lab.test",
                     f"git@github.com:{OWNER}/ansible-semaphore-guide.git",
                     "postgresql@16-main.service and getty@tty1.service",
                     "chacha20-poly1305@openssh.com and curve25519-sha256@libssh.org",
                     "@unittest.skipUnless and actions/checkout@v4 and react@18.3.1"):
            with self.subTest(text=text):
                self.assertEqual(self.rules(text), [])

    def test_ipv6_address_is_rejected_wherever_it_appears_in_prose(self):
        documentation, link_local = ":".join(["2001", "db8", "", "10"]), ":".join(["fe80", "", "1"])
        azure = ":".join(["2603", "1030", "7", "", "10"])
        for text in (documentation, f"Reach {link_local}.", f"[{documentation}]:22", f"({link_local}%eth0)",
                     azure, f"[{azure}]:22", f"http://[{azure}]/", "[" + ":".join(["2001", "", "1"]) + "]"):
            with self.subTest(text=text):
                self.assertIn(ADDRESS_RULE, self.rules(text))

    def test_ipv6_loopback_listen_specs_tunnels_times_and_hardware_addresses_are_accepted(self):
        for text in ("[::1]:3000 and ::1", "listen [::]:443", "ssh -L 8088:127.0.0.1:8088 host",
                     "at 10:30:00 or 2026-10-19T02:22:10Z", "52:54:00:12:34:56", "::ffff:127.0.0.1",
                     "std::vector", "|:---|:---:|", "words[::2] and words[1::2]", "rows[2:10:3]",
                     "data[a::b]", "x[10::5]", "words[3::2]"):
            with self.subTest(text=text):
                self.assertEqual(self.rules(text), [])

    def test_a_bracketed_ipv6_address_is_not_taken_for_a_slice(self):
        # Digits and colons alone, as in Azure's public IPv6 range, are still an address.
        for parts in (["2001", "db8", "", "1"], ["2603", "1030", "7", "", "10"]):
            with self.subTest(address=":".join(parts)):
                self.assertIn(ADDRESS_RULE, self.rules("[" + ":".join(parts) + "]:22"))

    def test_macos_and_windows_home_directories_are_rejected(self):
        for text in ("/Users/" + "someone/lab", "`/Users/" + "someone`", "C:" + "\\Users\\" + "someone\\.ssh",
                     "c:" + "\\Users\\" + "someone", '"C:' + "\\\\Users\\\\" + 'someone"'):
            with self.subTest(text=text):
                self.assertIn("personal workspace path", self.rules(text))

    def test_api_paths_and_home_placeholders_are_accepted(self):
        self.assertEqual(self.rules("/api/users/USER_ID, /users/me and /scim/v2/Users/ID"), [])
        self.assertEqual(self.rules("/Users/<you>/.ssh and C:\\Users\\<you>"), [])


class HeadingAnchorTests(unittest.TestCase):
    def test_comment_lines_in_fenced_examples_are_not_headings(self):
        text = "# Guide\n\n```bash\n# Pin the host key\nssh-keyscan host\n```\n\n## Check the key\n"
        self.assertEqual(validate.headings(text), {"guide", "check-the-key"})

    def test_a_link_to_a_comment_in_a_fenced_example_is_reported(self):
        target = "# Target\n\n```bash\n# Pin the host key\ntrue\n```\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for heading, expected in (("", ["unknown local heading anchor"]), ("## Pin the host key\n", [])):
                with self.subTest(heading=heading), mock.patch.object(validate, "ROOT", root):
                    (root / "target.md").write_text(target + heading)
                    validate.errors.clear()
                    validate.markdown(root / "page.md", "See [pinning](target.md#pin-the-host-key).\n")
                    found = [error.split(": ", 1)[1] for error in validate.errors]
                    validate.errors.clear()
                    self.assertEqual(found, expected)


class CloudInitTests(unittest.TestCase):
    """cloud-init runs these scripts at first boot, so a syntax error must fail validation."""

    def scripts(self, text):
        return list(validate.cloud_init_scripts(yaml.safe_load_all(text)))

    def test_the_onboarding_example_has_one_valid_script_and_one_key_placeholder(self):
        text = CLOUD_INIT.read_text()
        scripts = self.scripts(text)
        self.assertEqual(len(scripts), 1)
        result = subprocess.run(["bash", "-n"], input=scripts[0], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(text.count('"REPLACE_WITH_AUTOMATION_PUBLIC_KEY"'), 1)

    def test_string_and_shell_list_commands_are_checked_and_other_programs_are_not(self):
        text = ("#cloud-config\nbootcmd:\n  - echo early\nruncmd:\n  - [/bin/bash, -c, 'echo one']\n"
                "  - [sh, -c, 'echo two', arg0]\n  - [/usr/bin/systemctl, restart, ssh]\n")
        self.assertEqual(self.scripts(text), ["echo early", "echo one", "echo two"])
        self.assertEqual(self.scripts("#cloud-config\nruncmd:\n"), [])

    def test_a_syntax_error_in_the_first_boot_script_is_reported(self):
        text = CLOUD_INIT.read_text()
        # Without the script's last "fi", its final if never ends; the YAML still parses.
        head, fi, tail = text.rpartition("\n      fi\n")
        self.assertTrue(fi)
        broken = head + "\n" + tail
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name, content, expected in (("good.yaml", text, []),
                                            ("broken.yaml", broken, ["invalid Bash syntax (inspect locally)"])):
                with self.subTest(name=name):
                    path = root / name
                    path.write_text(content)
                    validate.errors.clear()
                    with mock.patch.object(validate, "ROOT", root), \
                            mock.patch.object(validate, "source_files", lambda: [path]), \
                            contextlib.redirect_stdout(io.StringIO()):
                        validate.main()
                    found = [error.split(": ", 1)[1] for error in validate.errors]
                    validate.errors.clear()
                    self.assertEqual(found, expected)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_the_onboarding_script_passes_shellcheck(self):
        for script in self.scripts(CLOUD_INIT.read_text()):
            result = subprocess.run(["shellcheck", "--shell=bash", "--severity=warning", "-"],
                                    input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout)


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


if __name__ == "__main__":
    unittest.main()
