"""Offline runs of onboard/new-vm/fill-cloud-init.sh, with and without its opt-in password hash.

The script prints cloud-init.yaml with the service key in place of its placeholder and, when
asked, one more write_files entry with the sudo password's SHA-512 hash. --with-password asks
on the controlling terminal, so those tests give it a pseudo-terminal as one. Nothing here
changes the system or contacts a host.
"""

import fcntl
import os
from pathlib import Path
import re
import select
import shutil
import stat
import subprocess
import tempfile
import termios
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
FILL = ROOT / "onboard" / "new-vm" / "fill-cloud-init.sh"
TEMPLATE = (ROOT / "onboard" / "new-vm" / "cloud-init.yaml").read_text()
PLACEHOLDER = '"REPLACE_WITH_AUTOMATION_PUBLIC_KEY"'
HASH_PATH = "/run/ansible-lab-onboard.hash"
BASH = shutil.which("bash")
# The shape of openssl passwd -6 output; not the hash of any password.
HASH = "$6$saltsalt$" + "a" * 86
ROUNDS_HASH = "$6$rounds=5000$saltsalt$" + "b" * 86
PROMPTS = "Sudo password for svc_ansible on the new VMs: \nThe same password again: \n"
GOOD_PASSWORD = "lab sudo password 42"


def first_boot_script(text):
    """The [/bin/bash, -c, SCRIPT] runcmd entry of a cloud-config text."""
    [script] = [entry[2] for entry in yaml.safe_load(text)["runcmd"] if isinstance(entry, list) and entry[1] == "-c"]
    return script


def section(text, start, end):
    """The lines from the first that contains start up to the next that contains end."""
    lines = text.splitlines(keepends=True)
    first = next(i for i, line in enumerate(lines) if start in line)
    last = next(i for i in range(first + 1, len(lines)) if end in lines[i])
    return "".join(lines[first:last])


@unittest.skipUnless(shutil.which("ssh-keygen"), "needs ssh-keygen")
class FillCloudInitTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "svc_ansible on the controller",
                        "-f", str(self.work / "svc_ansible")], check=True)
        self.key_file = self.work / "svc_ansible.pub"
        self.key = self.key_file.read_text().strip()

    def write(self, name, text):
        path = self.work / name
        path.write_text(text)
        return path

    def write_bytes(self, name, data):
        path = self.work / name
        path.write_bytes(data)
        return path

    def fill(self, *args, path=None):
        environment = dict(os.environ, LC_ALL="C")
        if path:
            environment["PATH"] = path
        return subprocess.run([BASH, str(FILL), *map(str, args)], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, env=environment, timeout=60, start_new_session=True)

    def default_output(self):
        return TEMPLATE.replace(PLACEHOLDER, f'"{self.key}"')

    def assertRefused(self, result, message, code=1):
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn(message, result.stderr)
        for secret in (HASH, ROUNDS_HASH, GOOD_PASSWORD):
            self.assertNotIn(secret, result.stderr)

    def hash_entry(self, text):
        """The one write_files entry for the hash file, after checking the rest of the file is unchanged."""
        data = yaml.safe_load(text)
        default = yaml.safe_load(self.default_output())
        # The anchor and its alias still resolve: the key's spare copy is the account's key.
        self.assertEqual(data["users"], default["users"])
        self.assertEqual(data["users"][1]["ssh_authorized_keys"], [self.key])
        paths = [entry["path"] for entry in data["write_files"]]
        self.assertEqual(paths, [entry["path"] for entry in default["write_files"]] + [HASH_PATH])
        spare = data["write_files"][paths.index("/run/ansible-lab-onboard.key")]
        self.assertEqual(spare["content"], self.key)
        self.assertEqual({key: value for key, value in data.items() if key != "write_files"},
                         {key: value for key, value in default.items() if key != "write_files"})
        # Right after the key's entry, and the only lines added.
        lines = text.splitlines(keepends=True)
        start = lines.index("    content: *automation_key\n") + 1
        added = lines[start:start + 6]
        self.assertEqual("".join(lines[:start] + lines[start + 6:]), self.default_output())
        self.assertTrue(added[0].startswith("  # ") and added[1].startswith("  # "), added)
        entry = data["write_files"][-1]
        self.assertEqual(set(entry), {"path", "owner", "permissions", "content"})
        self.assertEqual((entry["owner"], entry["permissions"]), ("root:root", "0600"))
        return entry["content"]

    def test_without_an_option_the_output_is_the_template_with_the_key(self):
        result = self.fill(self.key_file)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout, self.default_output())
        data = yaml.safe_load(result.stdout)
        self.assertEqual(data["users"][1]["ssh_authorized_keys"], [self.key])
        self.assertEqual(next(entry["content"] for entry in data["write_files"]
                              if entry["path"] == "/run/ansible-lab-onboard.key"), self.key)
        self.assertNotIn(f"path: {HASH_PATH}", result.stdout)
        self.assertNotIn("$6$", result.stdout)

    def test_the_template_has_no_hash_entry_and_no_second_placeholder(self):
        self.assertEqual(TEMPLATE.count(PLACEHOLDER), 1)
        self.assertEqual(re.findall(r"REPLACE_WITH_\w+", TEMPLATE), ["REPLACE_WITH_AUTOMATION_PUBLIC_KEY"] * 2)
        self.assertNotIn("$6$", TEMPLATE)
        self.assertEqual([entry["path"] for entry in yaml.safe_load(TEMPLATE)["write_files"]].count(HASH_PATH), 0)
        self.assertEqual(TEMPLATE.splitlines().count("    content: *automation_key"), 1)

    def test_the_hash_pattern_is_the_same_everywhere(self):
        pattern = re.compile(r"^\s*hash_pattern='([^']+)'$", re.M)
        copies = {
            "fill-cloud-init.sh": pattern.findall(FILL.read_text()),
            "cloud-init": pattern.findall(first_boot_script(TEMPLATE)),
            "onboard-linux.sh": pattern.findall((ROOT / "onboard" / "existing" / "onboard-linux.sh").read_text()),
        }
        for source, found in copies.items():
            self.assertEqual(found, copies["onboard-linux.sh"][:1], source)
        self.assertEqual(len(copies["onboard-linux.sh"]), 1)

    def test_a_hash_file_adds_one_root_only_entry_and_one_warning(self):
        for name, text, expected in (("plain", HASH + "\n", HASH), ("rounds", ROUNDS_HASH, ROUNDS_HASH),
                                     ("crlf", f"\n{HASH}\r\n\n", HASH)):
            with self.subTest(file=name):
                result = self.fill("--password-hash-file", self.write("hash", text), self.key_file)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.hash_entry(result.stdout), expected)
                self.assertEqual(result.stdout.count(expected), 1)
                self.assertEqual(result.stderr.count("warning"), 1)
                self.assertTrue(result.stderr.startswith("fill-cloud-init: warning: the filled file holds a hash"
                                                         " of the sudo password, which can be attacked offline."))
                for words in ("readable only by people who may have the password", "snippet folder",
                              "seed ISO", "/var/lib/cloud/instance/", "long random password", "never commit"):
                    self.assertIn(words, result.stderr)
                self.assertNotIn(expected, result.stderr)
        # The option may come after the key file too.
        result = self.fill(self.key_file, "--password-hash-file", self.write("hash", HASH))
        self.assertEqual(self.hash_entry(result.stdout), HASH)

    def test_with_a_hash_the_output_file_is_made_private_even_if_it_existed(self):
        # The shell empties a file that exists and keeps its mode; umask only shapes a new one.
        target = self.work / "onboard-new-vm.yaml"
        hash_file = self.write("hash", HASH)
        for start in (0o644, 0o664, None):
            with self.subTest(start=start):
                target.unlink(missing_ok=True)
                if start is not None:
                    target.write_text("an earlier copy without a secret\n")
                    target.chmod(start)
                old = os.umask(0o002)
                try:
                    with open(target, "w") as output:
                        result = subprocess.run([BASH, str(FILL), "--password-hash-file", str(hash_file),
                                                 str(self.key_file)], stdout=output, stderr=subprocess.PIPE,
                                                text=True, stdin=subprocess.DEVNULL, timeout=60)
                finally:
                    os.umask(old)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertEqual(self.hash_entry(target.read_text()), HASH)
        # Without a hash the file holds no secret, and its mode is the caller's business.
        target.chmod(0o644)
        with open(target, "w") as output:
            subprocess.run([BASH, str(FILL), str(self.key_file)], stdout=output, check=True, timeout=60)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
        self.assertEqual(target.read_text(), self.default_output())

    def test_refusals_print_nothing_on_standard_output(self):
        private = self.work / "svc_ansible"
        two = self.write("two.pub", f"{self.key}\n{self.key}\n")
        quote = self.write("quote.pub", self.key.rsplit(" ", 1)[0] + ' a"b\n')
        backslash = self.write("backslash.pub", self.key.rsplit(" ", 1)[0] + " a\\b\n")
        not_a_key = self.write("not-a-key.pub", "ssh-ed25519 AAAAnotbase64!\n")
        cases = {
            "no key file": ((), "Usage:", 2),
            "two key files": ((self.key_file, self.key_file), "Usage:", 2),
            "unknown option": (("--password", self.key_file), "Usage:", 2),
            "hash file without a value": ((self.key_file, "--password-hash-file"), "Usage:", 2),
            "both options": (("--with-password", "--password-hash-file", self.write("hash", HASH), self.key_file),
                             "Usage:", 2),
            "missing key file": ((self.work / "missing.pub",), "cannot read", 1),
            "empty key file": ((self.write("empty.pub", "\n"),), "must hold exactly one public key line", 1),
            "two keys": ((two,), "must hold exactly one public key line, and it holds 2", 1),
            "a comment beyond ASCII": ((self.write_bytes("latin.pub", self.key.rsplit(" ", 1)[0].encode() + b" jos\xe9\n"),),
                                       "the key comment has characters other than plain ASCII", 1),
            "a comment in UTF-8": ((self.write("utf8.pub", self.key.rsplit(" ", 1)[0] + " josé@laptop\n"),),
                                   "the key comment has characters other than plain ASCII", 1),
            "private key": ((private,), "must hold exactly one public key line", 1),
            "not a key": ((not_a_key,), "is not a single-line OpenSSH public key", 1),
            'a " in the comment': ((quote,), 'the key comment contains a " or a \\', 1),
            "a \\ in the comment": ((backslash,), 'the key comment contains a " or a \\', 1),
            "missing hash file": (("--password-hash-file", self.work / "missing", self.key_file), "cannot read", 1),
        }
        bad_hashes = {
            "empty": "\n",
            "MD5 crypt": "$1$saltsalt$" + "a" * 22,
            "short": "$6$saltsalt$" + "a" * 85,
            "rounds out of range": "$6$rounds=999$saltsalt$" + "a" * 86,
            "two lines": f"{HASH}\n{HASH}\n",
            "locked": "!" + HASH,
            "a quote": HASH[:-1] + '"',
            "a password": GOOD_PASSWORD,
        }
        for name, text in bad_hashes.items():
            cases[f"hash: {name}"] = (("--password-hash-file", self.write(name.replace(" ", "-"), text), self.key_file),
                                      "must hold one line: a SHA-512 crypt hash from openssl passwd -6", 1)
        for name, (args, message, code) in cases.items():
            with self.subTest(case=name):
                self.assertRefused(self.fill(*args), message, code)

    def test_a_hash_is_never_printed_to_a_terminal(self):
        master, terminal = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, terminal)
        # --with-password refuses before it asks, so no password is typed in vain.
        for option in (("--password-hash-file", str(self.write("hash", HASH))), ("--with-password",)):
            with self.subTest(option=option[0]):
                result = subprocess.run([BASH, str(FILL), *option, str(self.key_file)], stdout=terminal,
                                        stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, timeout=60)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "fill-cloud-init: with a password hash, send the output to a file:"
                                                " ... > ~/onboard-new-vm.yaml\n")
                self.assertFalse(select.select([master], [], [], 0.2)[0])

    def test_with_password_needs_a_terminal(self):
        # The test's own session has no controlling terminal: there is none to ask on.
        self.assertRefused(self.fill("--with-password", self.key_file),
                           "--with-password asks on a terminal, and there is none; use --password-hash-file")

    def test_the_hash_reaches_the_first_boot_script_which_sets_it_and_removes_it(self):
        result = self.fill("--password-hash-file", self.write("hash", HASH), self.key_file)
        data = yaml.safe_load(result.stdout)
        script = first_boot_script(result.stdout)
        block = section(script, "# fill-cloud-init.sh --with-password adds", "# cloud-init drops a key")
        hash_file = self.work / "ansible-lab-onboard.hash"
        # As cloud-init writes it: the entry's content, without a newline, mode 0600.
        entry = data["write_files"][-1]
        hash_file.write_text(entry["content"])
        hash_file.chmod(int(entry["permissions"], 8))
        self.assertEqual(block.count(HASH_PATH), 1)
        block = block.replace(HASH_PATH, str(hash_file))
        bin_dir = self.work / "bin"
        bin_dir.mkdir()
        stand_ins = {"chpasswd": 'cat >"$SHADOW"', "getent": 'cat "$SHADOW"'}
        for name, body in stand_ins.items():
            (bin_dir / name).write_text("#!/bin/sh\n" + body + "\n")
            (bin_dir / name).chmod(0o755)
        run = subprocess.run([BASH, "-c", 'set -u\nfailed=\nproblem() { echo "onboard: ERROR: $*"; failed=yes; }\n'
                              + block + 'echo "failed=$failed password_set=$password_set"\n'],
                             capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, LC_ALL="C", PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                                      SHADOW=str(self.work / "shadow")))
        self.assertEqual(run.stdout, "onboard: set svc_ansible's sudo password from the hash fill-cloud-init.sh"
                                     " added\nfailed= password_set=yes\n", run.stderr)
        self.assertEqual((self.work / "shadow").read_text(), f"svc_ansible:{HASH}\n")
        self.assertFalse(hash_file.exists())


@unittest.skipUnless(hasattr(termios, "TIOCSCTTY") and shutil.which("openssl") and shutil.which("ssh-keygen"),
                     "needs a pseudo-terminal, openssl and ssh-keygen")
class WithPasswordTests(unittest.TestCase):
    """--with-password on a pseudo-terminal that is the script's controlling terminal, as the operator's is."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "svc_ansible",
                        "-f", str(self.work / "svc_ansible")], check=True)
        self.key_file = self.work / "svc_ansible.pub"

    def answer(self, *answers, path=None):
        """Run with --with-password and type each answer after its prompt, once echo is off.

        None ends the input with Ctrl-D. Returns the exit code, standard output, standard
        error and whatever the terminal echoed.
        """
        master, terminal = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, terminal)
        environment = dict(os.environ, LC_ALL="C")
        if path:
            environment["PATH"] = path
        process = subprocess.Popen([BASH, str(FILL), "--with-password", str(self.key_file)], stdin=terminal,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                                   start_new_session=True, preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        self.addCleanup(lambda: process.poll() is None and process.kill())
        stderr = b""
        for count, answer in enumerate(answers, 1):
            # The prompt, then read -s turning echo off, before the answer is typed.
            while stderr.count(b": ") < count or termios.tcgetattr(terminal)[3] & termios.ECHO:
                if process.poll() is not None:
                    break
                if select.select([process.stderr], [], [], 0.05)[0]:
                    stderr += os.read(process.stderr.fileno(), 4096)
            if process.poll() is not None:
                break
            os.write(master, b"\x04" if answer is None else answer.encode() + b"\n")
        stdout, rest = process.communicate(timeout=60)
        echoed = b""
        while select.select([master], [], [], 0.1)[0]:
            try:
                echoed += os.read(master, 4096)
            except OSError:
                break
        return process.returncode, stdout.decode(), (stderr + rest).decode(), echoed.decode(errors="replace")

    def test_a_good_password_is_hashed_and_never_shown(self):
        code, stdout, stderr, echoed = self.answer(GOOD_PASSWORD, GOOD_PASSWORD)
        self.assertEqual(code, 0, stderr)
        self.assertTrue(stderr.startswith(PROMPTS), stderr)
        self.assertEqual(stderr.count("warning"), 1)
        entry = yaml.safe_load(stdout)["write_files"][-1]
        self.assertEqual((entry["path"], entry["permissions"]), (HASH_PATH, "0600"))
        password_hash = entry["content"]
        self.assertRegex(password_hash, r"^\$6\$[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}$")
        salt = password_hash.split("$")[2]
        check = subprocess.run(["openssl", "passwd", "-6", "-salt", salt, "-stdin"], input=GOOD_PASSWORD + "\n",
                               capture_output=True, text=True, check=True)
        self.assertEqual(check.stdout.strip(), password_hash)
        for text in (stdout, stderr, echoed):
            self.assertNotIn(GOOD_PASSWORD, text)

    def test_bad_answers_are_refused(self):
        cases = {
            "differ": ((GOOD_PASSWORD, GOOD_PASSWORD + "!"), "the two passwords differ; nothing was printed"),
            "empty": (("", ""), "the password is empty; nothing was printed"),
            "eleven characters": (("a" * 11, "a" * 11), "the password has fewer than 12 characters"),
            "Ctrl-D": ((None,), "no password was given"),
        }
        if "c.utf8" in subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.lower():
            # Characters, not bytes, as the playbook counts them: twelve bytes, six characters.
            cases["six two-byte characters"] = (("é" * 6, "é" * 6), "the password has fewer than 12 characters")
        for name, (answers, message) in cases.items():
            with self.subTest(case=name):
                code, stdout, stderr, echoed = self.answer(*answers)
                self.assertEqual((code, stdout), (1, ""), stderr)
                self.assertIn("fill-cloud-init: " + message, stderr)
                self.assertNotIn("warning", stderr)
        code, stdout, stderr, _ = self.answer("é" * 12, "é" * 12)
        self.assertEqual(code, 0, stderr)

    def test_a_failed_hash_prints_nothing(self):
        bin_dir = self.work / "bin"
        bin_dir.mkdir()
        (bin_dir / "openssl").write_text("#!/bin/sh\ncat >/dev/null\necho not-a-hash\n")
        (bin_dir / "openssl").chmod(0o755)
        code, stdout, stderr, _ = self.answer(GOOD_PASSWORD, GOOD_PASSWORD,
                                              path=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        self.assertEqual((code, stdout), (1, ""), stderr)
        self.assertIn("openssl passwd -6 did not make a SHA-512 crypt hash", stderr)


if __name__ == "__main__":
    unittest.main()
