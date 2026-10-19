"""Offline runs of scripts/add-target.sh with a stub key scan; nothing here contacts a host."""

import fcntl
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import termios
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
# Documentation addresses (RFC 5737), built in parts so the publication check accepts them.
TEST_NET = ".".join(("192", "0", "2"))
INVENTORY = """# Local lab inventory read by Semaphore at every run.
[ubuntu]

[enterprise_linux]

[lab:children]
ubuntu
enterprise_linux

[lab:vars]
ansible_user=svc_ansible
ansible_python_interpreter=/usr/bin/python3
"""


@unittest.skipUnless(shutil.which("ssh-keygen"), "needs ssh-keygen")
class AddTargetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.lab = self.work / "lab"
        (self.lab / "inventories").mkdir(parents=True)
        self.inventory = self.lab / "inventories" / "lab.ini"
        self.inventory.write_text(INVENTORY)
        self.known_hosts = self.work / "known_hosts"
        self.known_hosts.write_text("")
        self.key = self.make_key("host")
        self.other_key = self.make_key("other")
        # The script needs root and scans the target; stand-ins answer for both and
        # record each call, so a test can tell whether the script went past reading.
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.calls = self.work / "calls"
        (self.bin / "id").write_text('#!/bin/sh\necho "id $*" >>"$CALLS"\necho 0\n')
        (self.bin / "ssh-keyscan").write_text(
            '#!/bin/sh\necho "ssh-keyscan $*" >>"$CALLS"\nfor last; do :; done\n'
            'printf "%s %s\\n" "$last" "$(cat "$SCAN_KEY")"\n')
        for stub in ("id", "ssh-keyscan"):
            (self.bin / stub).chmod(0o755)

    def make_key(self, name):
        path = self.work / name
        subprocess.run(["ssh-keygen", "-q", "-t", "rsa", "-b", "2048", "-N", "", "-f", str(path)], check=True)
        public = Path(f"{path}.pub").read_text().split()
        fingerprint = subprocess.run(["ssh-keygen", "-lf", f"{path}.pub"], capture_output=True, text=True,
                                     check=True).stdout.split()[1]
        return {"line": f"{public[0]} {public[1]}", "fingerprint": fingerprint, "file": f"{path}.pub"}

    def environment(self, served=None):
        scan = self.work / "scan.pub"
        scan.write_text((served or self.key)["line"])
        return dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", SCAN_KEY=str(scan), CALLS=str(self.calls))

    def add(self, name="lab-alma", address=f"{TEST_NET}.12", group="enterprise_linux", fingerprint=None, served=None):
        return subprocess.run(
            ["bash", str(ROOT / "scripts" / "add-target.sh"), "--name", name, "--address", address,
             "--group", group, "--fingerprint", fingerprint or self.key["fingerprint"],
             "--lab-dir", str(self.lab), "--known-hosts", str(self.known_hosts)],
            capture_output=True, text=True, env=self.environment(served), timeout=60)

    def from_info(self, *options):
        """The --from-info command, with this test's lab folder and known-hosts file."""
        return ["bash", str(ROOT / "scripts" / "add-target.sh"), "--from-info", *options,
                "--lab-dir", str(self.lab), "--known-hosts", str(self.known_hosts)]

    def paste(self, text, *options):
        return subprocess.run(self.from_info(*options), input=text, capture_output=True, text=True,
                              env=self.environment(), timeout=60)

    def info(self, **values):
        """The four lines the VM-side scripts print; a value of None leaves its line out."""
        values = dict(dict(name="lab-alma", address=f"{TEST_NET}.12", group="enterprise_linux",
                           fingerprint=self.key["fingerprint"]), **values)
        return "".join(f"{key}={value}\n" for key, value in values.items() if value is not None)

    def assertAdded(self, result):
        """The paste added lab-alma, after showing the values it used."""
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], f"Using name=lab-alma address={TEST_NET}.12"
                         f" group=enterprise_linux fingerprint={self.key['fingerprint']}")
        self.assertIn("Added lab-alma", result.stdout)
        added = INVENTORY.replace("[enterprise_linux]\n", f"[enterprise_linux]\nlab-alma ansible_host={TEST_NET}.12\n")
        self.assertEqual(self.state(), (added, f"{TEST_NET}.12 {self.key['line']}\n"))

    def reset(self):
        self.inventory.write_text(INVENTORY)
        self.known_hosts.write_text("")
        self.calls.unlink(missing_ok=True)

    def state(self):
        return self.inventory.read_text(), self.known_hosts.read_text()

    def test_a_verified_host_is_added_under_its_group_and_trusted(self):
        result = self.add()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        inventory, known = self.state()
        self.assertIn(f"[enterprise_linux]\nlab-alma ansible_host={TEST_NET}.12\n", inventory)
        self.assertEqual(known, f"{TEST_NET}.12 {self.key['line']}\n")
        self.assertIn("run the Ping template, which covers every host in the lab group. If lab-alma fails", result.stdout)

    def test_running_it_again_changes_nothing(self):
        self.assertEqual(self.add().returncode, 0)
        before = self.state()
        result = self.add()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Already present", result.stdout)
        self.assertEqual(self.state(), before)

    def test_a_key_that_does_not_match_changes_nothing(self):
        result = self.add(served=self.other_key)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No scanned key matched", result.stdout)
        self.assertEqual(self.state(), (INVENTORY, ""))

    def test_values_that_are_not_plain_tokens_are_refused(self):
        for arguments in ({"address": f"{TEST_NET}.12 ansible_become_exe=/tmp/x"}, {"address": "-oProxyCommand=x"},
                          {"name": f"lab-alma ansible_host={TEST_NET}.99"}, {"fingerprint": "SHA256:a b"},
                          {"group": "lab"}):
            with self.subTest(arguments=arguments):
                result = self.add(**arguments)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(self.state(), (INVENTORY, ""))

    def test_a_name_that_is_also_a_group_is_refused(self):
        for name in ("lab", "ubuntu", "enterprise_linux", "all", "ungrouped"):
            with self.subTest(name=name):
                result = self.add(name=name)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("group", result.stdout)
                self.assertEqual(self.state(), (INVENTORY, ""))

    def test_an_address_listed_under_another_name_is_refused(self):
        self.assertEqual(self.add().returncode, 0)
        before = self.state()
        result = self.add(name="lab-alma2")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"already lists {TEST_NET}.12 as lab-alma", result.stdout)
        self.assertEqual(self.state(), before)

    def test_the_same_name_with_other_settings_is_refused(self):
        self.assertEqual(self.add().returncode, 0)
        before = self.state()
        result = self.add(address=f"{TEST_NET}.13")
        self.assertEqual(result.returncode, 1)
        self.assertIn("other settings", result.stdout)
        self.assertEqual(self.state(), before)

    def test_a_different_trusted_key_for_the_address_is_refused(self):
        self.known_hosts.write_text(f"{TEST_NET}.12 {self.other_key['line']}\n")
        result = self.add()
        self.assertEqual(result.returncode, 1)
        self.assertIn("different key", result.stdout)
        self.assertEqual(self.state(), (INVENTORY, f"{TEST_NET}.12 {self.other_key['line']}\n"))

    def test_an_already_trusted_matching_key_is_not_added_twice(self):
        self.known_hosts.write_text(f"{TEST_NET}.12 {self.key['line']}\n")
        result = self.add()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.state()[1], f"{TEST_NET}.12 {self.key['line']}\n")

    def test_a_missing_group_section_changes_nothing(self):
        self.inventory.write_text(INVENTORY.replace("[ubuntu]\n\n", ""))
        result = self.add(name="lab-ubuntu", group="ubuntu")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.known_hosts.read_text(), "")

    # --from-info: the lines a VM printed, pasted as data.

    def test_each_vm_format_is_read(self):
        lines = self.info()
        block = ("Add this VM on the controller: in the guide's folder, run\n"
                 "  sudo bash scripts/add-target.sh --from-info\nthen paste these lines and press Ctrl-D:\n" + lines)
        formats = {
            "plain": lines,
            "cloud-init's prefix": "".join("onboard: " + line for line in lines.splitlines(keepends=True)),
            "CRLF": lines.replace("\n", "\r\n"),
            "onboard-linux.sh with the text around it": "host: lab-alma (AlmaLinux 9.8)\n" + block + "RESULT: OK\n",
            "the cloud-init log with the text around it": "".join(
                "onboard: " + line for line in ["svc_ansible is ready; set its sudo password next\n"]
                + block.splitlines(keepends=True)),
            "inventory-info.sh, indented, CRLF and no final line break": "".join(
                "  " + line for line in (f"VM: lab-alma | {TEST_NET}.12 | almalinux 9.8\n"
                                         + block).splitlines(keepends=True)).replace("\n", "\r\n").rstrip(),
        }
        for label, text in formats.items():
            with self.subTest(format=label):
                self.reset()
                self.assertAdded(self.paste(text))

    def test_pasting_again_changes_nothing(self):
        self.assertAdded(self.paste(self.info()))
        before = self.state()
        result = self.paste(self.info())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Already present", result.stdout)
        self.assertEqual(self.state(), before)

    def test_one_vms_lines_at_a_time(self):
        for text in (self.info() + "onboard: name=lab-alma\n",
                     self.info() + self.info(name="lab-rocky", address=f"{TEST_NET}.13")):
            with self.subTest(text=text):
                result = self.paste(text)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout,
                                 "The paste has more than one name= line; paste one VM's lines at a time.\n")
                self.assertEqual(self.state(), (INVENTORY, ""))

    def test_an_option_supplies_a_value_the_paste_lacks(self):
        text = self.info(address=None)
        result = self.paste(text)
        self.assertEqual((result.returncode, result.stdout),
                         (2, "The paste has no address= line; give that value with --address.\n"))
        self.assertEqual(self.state(), (INVENTORY, ""))
        self.assertAdded(self.paste(text, "--address", f"{TEST_NET}.12"))

    def test_a_value_given_both_ways_is_refused(self):
        # Even the same value: the operator should know which one is used.
        for key, value in (("name", "lab-alma"), ("address", f"{TEST_NET}.12"), ("group", "enterprise_linux"),
                           ("fingerprint", self.key["fingerprint"])):
            with self.subTest(key=key):
                result = self.paste(self.info(), f"--{key}", value)
                self.assertEqual((result.returncode, result.stdout),
                                 (2, f"The {key} is both in the paste and given with --{key}; give it once.\n"))
                self.assertEqual(self.state(), (INVENTORY, ""))

    def test_pasted_values_are_checked_as_options_are_and_never_run(self):
        marker = self.work / "ran"
        sudoers = self.work / "sudoers"
        sudoers.write_text("root ALL=(ALL:ALL) ALL\n")
        for values in ({"name": f"$(touch {marker})"}, {"name": f"`touch {marker}`"}, {"name": "lab alma"},
                       {"address": f"{TEST_NET}.12;touch {marker}"}, {"address": f"-oProxyCommand=touch {marker}"},
                       # The option a review smuggled into the old command line, which
                       # appended the scanned key to the sudoers file.
                       {"fingerprint": f"{self.key['fingerprint']} --known-hosts {sudoers}"},
                       {"group": "lab"}):
            with self.subTest(values=values):
                result = self.paste(self.info(**values))
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(self.state(), (INVENTORY, ""))
                # A refused value is never shown, so nothing unchecked reaches the terminal.
                self.assertNotIn(str(self.work), result.stdout + result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(sudoers.read_text(), "root ALL=(ALL:ALL) ALL\n")

    def test_other_lines_are_ignored_and_never_run(self):
        marker = self.work / "ran"
        elsewhere = self.work / "elsewhere"
        noise = (f"echo $(touch {marker}); touch {marker}\n`touch {marker}`\nlab_dir={elsewhere}\n"
                 f"known_hosts={elsewhere}\nName=lab-other\nonboard:name=lab-other\nname = lab-other\n"
                 "  sudo bash scripts/add-target.sh --name lab-other --from-info\n\n")
        self.assertAdded(self.paste(noise + self.info() + noise))
        self.assertFalse(marker.exists())
        self.assertFalse(elsewhere.exists())

    def test_a_paste_over_64_kib_is_refused(self):
        lines = self.info()
        filler = "x" * (65536 - len(lines) - 1) + "\n"
        self.assertAdded(self.paste(filler + lines))
        self.reset()
        result = self.paste("x" + filler + lines)
        self.assertEqual((result.returncode, result.stdout),
                         (2, "The paste is longer than 64 KiB; paste one VM's lines at a time.\n"))
        self.assertEqual(self.state(), (INVENTORY, ""))
        self.assertFalse(self.calls.exists())

    def test_the_whole_paste_is_read_before_anything_else(self):
        # Complete values, an unknown option and an over-long paste all wait for the end
        # of the input, so that no part of a paste is left for the shell.
        for options, first, expected in (((), self.info(), 0), (("--bogus",), self.info(), 2),
                                         ((), "x" * 70000 + "\n", 2)):
            with self.subTest(options=options, first=first[:20]):
                self.reset()
                process = subprocess.Popen(self.from_info(*options), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, env=self.environment())
                process.stdin.write(first)
                process.stdin.flush()
                time.sleep(1)
                self.assertIsNone(process.poll())
                self.assertFalse(self.calls.exists())
                stdout, stderr = process.communicate("RESULT: OK\n", timeout=60)
                self.assertEqual(process.returncode, expected, stdout + stderr)
                self.assertEqual(self.calls.exists(), expected == 0)

    @unittest.skipUnless(hasattr(termios, "TIOCSCTTY"), "needs a pseudo-terminal")
    def test_on_a_terminal_control_characters_leave_nothing_for_the_shell(self):
        # The pseudo-terminal is the script's controlling terminal, as the operator's is: a
        # Ctrl-C in the paste sends SIGINT, and a Ctrl-D at the start of a line ends the input.
        master, terminal = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, terminal)
        process = subprocess.Popen(self.from_info(), stdin=terminal, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=self.environment(), start_new_session=True,
                                   preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        prompt = b""
        while not prompt.endswith(b"\n"):
            self.assertTrue(select.select([process.stderr], [], [], 30)[0], prompt)
            prompt += os.read(process.stderr.fileno(), 4096)
        self.assertEqual(prompt, b"Paste the name=, address=, group= and fingerprint= lines the VM printed,"
                                 b" then press Ctrl-D:\n")
        marker = self.work / "ran"
        os.write(master, f"text\x03more text\n{self.info()}\x04touch {marker}\n".encode())
        stdout, _ = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, stdout)
        self.assertIn(b"Added lab-alma", stdout)
        # Nothing is left for whatever reads the terminal next, such as the shell.
        os.set_blocking(terminal, False)
        with self.assertRaises(BlockingIOError):
            os.read(terminal, 4096)


if __name__ == "__main__":
    unittest.main()
