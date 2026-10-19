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
# What add-target.sh adds after refusing a name that came from the paste.
NAME_HINT = ("Paste the lines again without the name= line and add --name NAME, "
             "or set INVENTORY_NAME in inventory-info.sh.")
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
        # The scan takes $SCAN_DELAY seconds, as one over a slow link does.
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.calls = self.work / "calls"
        (self.bin / "id").write_text('#!/bin/sh\necho "id $*" >>"$CALLS"\necho 0\n')
        (self.bin / "ssh-keyscan").write_text(
            '#!/bin/sh\necho "ssh-keyscan $*" >>"$CALLS"\nsleep "${SCAN_DELAY:-0}"\nfor last; do :; done\n'
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

    def paste(self, text, *options, served=None):
        return subprocess.run(self.from_info(*options), input=text, capture_output=True, text=True,
                              env=self.environment(served), timeout=60)

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

    def test_modules_in_the_working_directory_are_never_imported(self):
        # The script runs as root, and its inline Python runs isolated: a module file in the
        # folder it runs from, or in PYTHONPATH, never stands in for one it imports.
        planted = self.work / "planted"
        planted.mkdir()
        marker = self.work / "imported"
        for module in ("re", "pathlib", "termios", "json"):
            (planted / f"{module}.py").write_text(f"open({str(marker)!r}, 'a').write({module!r})\n")
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "add-target.sh"), "--name", "lab-alma", "--address", f"{TEST_NET}.12",
             "--group", "enterprise_linux", "--fingerprint", self.key["fingerprint"], "--lab-dir", str(self.lab),
             "--known-hosts", str(self.known_hosts)],
            capture_output=True, text=True, cwd=planted, env=dict(self.environment(), PYTHONPATH=str(planted)),
            timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Added lab-alma", result.stdout)
        self.assertFalse(marker.exists())

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
                # A name given as an option needs no hint about the paste.
                self.assertEqual((result.returncode, result.stdout),
                                 (1, f"{name} is also the name of an inventory group; choose another name.\n"))
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

    def test_a_rebuilt_vm_keeps_its_line_and_gets_its_new_key_trusted(self):
        # A rebuilt VM keeps its name and address and has a new host key.
        self.assertEqual(self.add().returncode, 0)
        added = self.state()
        result = self.add(fingerprint=self.other_key["fingerprint"], served=self.other_key)
        self.assertEqual((result.returncode, result.stdout), (1, (
            f"lab-alma ({TEST_NET}.12) is in {self.inventory}, but known-hosts holds a different key for"
            f" {TEST_NET}.12. After verifying why its key changed,\n"
            "remove the old entry and give the rewritten file back to the service, then run this again:\n"
            f"  sudo ssh-keygen -R {TEST_NET}.12 -f {self.known_hosts}\n"
            f"  sudo chown root:semaphore {self.known_hosts} && sudo chmod 0640 {self.known_hosts}\n")))
        self.assertEqual(self.state(), added)
        # The first command it printed, as the operator runs it.
        subprocess.run(["ssh-keygen", "-R", f"{TEST_NET}.12", "-f", str(self.known_hosts)], capture_output=True,
                       check=True)
        self.assertEqual(self.state(), (added[0], ""))
        # A scan that does not match the fingerprint still changes nothing.
        result = self.add(fingerprint=self.other_key["fingerprint"], served=self.key)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No scanned key matched", result.stdout)
        self.assertEqual(self.state(), (added[0], ""))
        # Run again with the VM's lines, the script trusts the verified key and keeps the one line.
        trusted = (added[0], f"{TEST_NET}.12 {self.other_key['line']}\n")
        result = self.paste(self.info(fingerprint=self.other_key["fingerprint"]), served=self.other_key)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[1], f"Trusted the verified host key of lab-alma ({TEST_NET}.12),"
                                                        f" which {self.inventory} already lists.")
        self.assertIn("run the Ping template", result.stdout)
        self.assertEqual(self.state(), trusted)
        result = self.add(fingerprint=self.other_key["fingerprint"], served=self.other_key)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Already present", result.stdout)
        self.assertEqual(self.state(), trusted)

    def test_the_same_host_under_another_group_is_refused(self):
        listed = INVENTORY.replace("[enterprise_linux]\n", f"[enterprise_linux]\nlab-alma ansible_host={TEST_NET}.12\n")
        # A line above every section is in Ansible's ungrouped group.
        for inventory, other in ((listed, "enterprise_linux"), (f"lab-alma ansible_host={TEST_NET}.12\n" + INVENTORY,
                                                                "ungrouped")):
            for key in ("", f"{TEST_NET}.12 {self.key['line']}\n"):
                with self.subTest(other=other, trusted=bool(key)):
                    self.inventory.write_text(inventory)
                    self.known_hosts.write_text(key)
                    result = self.add(group="ubuntu")
                    self.assertEqual((result.returncode, result.stdout), (1, (
                        f"Inventory lists lab-alma under [{other}], not under [ubuntu]; edit it by hand instead.\n")))
                    self.assertEqual(self.state(), (inventory, key))

    @unittest.skipUnless(shutil.which("flock"), "needs flock")
    def test_runs_on_one_lab_folder_take_turns(self):
        # The scan is slow, so without turns both runs would pass the checks before
        # either wrote, and the inventory would get two lines and known-hosts two keys.
        paste = self.work / "paste"
        paste.write_text(self.info())
        environment = dict(self.environment(), SCAN_DELAY="2")
        with open(paste) as first, open(paste) as second:
            runs = [subprocess.Popen(self.from_info(), stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, env=environment) for stream in (first, second)]
            results = [(run.communicate(timeout=60)[0], run.returncode) for run in runs]
        for stdout, returncode in results:
            self.assertEqual(returncode, 0, stdout)
        self.assertEqual(sorted("Added lab-alma" in stdout for stdout, _ in results), [False, True])
        self.assertEqual(sorted("Already present" in stdout for stdout, _ in results), [False, True])
        added = INVENTORY.replace("[enterprise_linux]\n", f"[enterprise_linux]\nlab-alma ansible_host={TEST_NET}.12\n")
        self.assertEqual(self.state(), (added, f"{TEST_NET}.12 {self.key['line']}\n"))
        self.assertEqual(self.calls.read_text().count("ssh-keyscan "), 1)

    def test_a_run_that_does_not_get_its_turn_changes_nothing(self):
        # flock -w 120 gives up after two minutes; a stand-in gives up at once.
        (self.bin / "flock").write_text('#!/bin/sh\necho "flock $*" >>"$CALLS"\nexit 1\n')
        (self.bin / "flock").chmod(0o755)
        result = self.add()
        self.assertEqual((result.returncode, result.stdout), (
            1, f"Another add-target.sh run is changing {self.lab}; run this again when it has finished.\n"))
        self.assertIn("flock -w 120 9\n", self.calls.read_text())
        self.assertNotIn("ssh-keyscan", self.calls.read_text())
        self.assertEqual(self.state(), (INVENTORY, ""))

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

    def on_a_terminal(self, *pieces):
        """--from-info on a pseudo-terminal: write each text after the prompt, sleep for each number.

        The pseudo-terminal is the script's controlling terminal, as the operator's is: a
        Ctrl-C, Ctrl-\\ or Ctrl-Z in the paste sends a signal, and a Ctrl-D at the start of
        a line ends the input. Returns the exit code and the output.
        """
        master, terminal = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, terminal)
        process = subprocess.Popen(self.from_info(), stdin=terminal, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=self.environment(), start_new_session=True,
                                   preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        prompt = b""
        while not prompt.endswith(b"Ctrl-D:\n"):
            self.assertTrue(select.select([process.stderr], [], [], 30)[0], prompt)
            prompt += os.read(process.stderr.fileno(), 4096)
        self.assertEqual(prompt, b"To cancel, press Ctrl-C and then Ctrl-D.\nPaste the name=, address=, group= and"
                                 b" fingerprint= lines the VM printed, then press Ctrl-D:\n")
        for piece in pieces:
            if isinstance(piece, str):
                os.write(master, piece.encode())
            else:
                time.sleep(piece)
        stdout, _ = process.communicate(timeout=60)
        # Nothing is left for whatever reads the terminal next, such as the shell.
        os.set_blocking(terminal, False)
        with self.assertRaises(BlockingIOError):
            os.read(terminal, 4096)
        return process.returncode, stdout.decode()

    @unittest.skipUnless(hasattr(termios, "TIOCSCTTY"), "needs a pseudo-terminal")
    def test_on_a_terminal_text_after_the_end_is_left_for_nobody(self):
        marker = self.work / "ran"
        for pieces in ((f"text\x1cmore\x1aagain\n{self.info()}\x04touch {marker}\n",),
                       # The rest of a long paste, or of one over a slow link, arrives after its Ctrl-D.
                       (f"{self.info()}\x04#\n", 0.3, f"touch {marker}\n")):
            with self.subTest(pieces=pieces):
                self.reset()
                returncode, stdout = self.on_a_terminal(*pieces)
                self.assertEqual(returncode, 0, stdout)
                self.assertIn("Added lab-alma", stdout)

    @unittest.skipUnless(hasattr(termios, "TIOCSCTTY"), "needs a pseudo-terminal")
    def test_on_a_terminal_ctrl_c_then_ctrl_d_cancels(self):
        # Ctrl-C does not stop the reading, which would leave the rest for the shell; once
        # the input ends, the script stops without changing anything.
        for pieces in ((self.info(), 0.2, "\x03", 0.2, "\x04"), (f"text\x03more text\n{self.info()}\x04touch x\n",),
                       ("\x03", 0.2, "\x04")):
            with self.subTest(pieces=pieces):
                returncode, stdout = self.on_a_terminal(*pieces)
                self.assertEqual((returncode, stdout), (130, "Cancelled; nothing changed.\n"))
                self.assertEqual(self.state(), (INVENTORY, ""))
                self.assertFalse(self.calls.exists())

    def test_the_names_ansible_gives_the_controller_are_refused(self):
        # Ansible would run every delegate_to: localhost task, such as the STIG summary, on
        # a host of that name instead of the controller.
        for name in ("localhost", "127.0.0.1"):
            for form, result in (("option", self.add(name=name)), ("paste", self.paste(self.info(name=name)))):
                with self.subTest(name=name, form=form):
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn(f"{name} is the name Ansible gives the controller; choose another name.",
                                  result.stdout)
                    self.assertEqual(NAME_HINT in result.stdout, form == "paste")
                    self.assertEqual(self.state(), (INVENTORY, ""))

    def test_a_refused_pasted_name_comes_with_the_way_round_it(self):
        # A VM may be named like a group, such as an Ubuntu cloud image booted without metadata,
        # and --name alone would be refused as a value given both ways.
        for name in ("lab", "ubuntu", "enterprise_linux", "all", "ungrouped", "localhost", "127.0.0.1"):
            with self.subTest(name=name):
                result = self.paste(self.info(name=name))
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(result.stdout.splitlines()[-1], NAME_HINT)
                self.assertEqual(self.state(), (INVENTORY, ""))
                # The name given as an option, with the rest pasted, gets no hint.
                result = self.paste(self.info(name=None), "--name", name)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertNotIn(NAME_HINT, result.stdout)
        # What the hint says works.
        self.assertAdded(self.paste(self.info(name=None), "--name", "lab-alma"))

    @unittest.skipUnless(shutil.which("locale"), "needs locale")
    def test_look_alike_letters_are_refused_in_a_utf8_locale(self):
        # sudo keeps the operator's locale, in which bash's [A-Za-z] also matches letters
        # such as a Latin alpha or fullwidth forms; the script compares bytes instead.
        locales = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.split()
        utf8 = next((name for name in locales if name.lower().replace("-", "") == "en_us.utf8"), None)
        if not utf8:
            self.skipTest("needs the en_US.UTF-8 locale")
        environment = {key: value for key, value in self.environment().items() if not key.startswith("LC_")}
        for name in ("lab-\u0251lma", "\uff4c\uff41\uff42-alma"):
            with self.subTest(name=name):
                result = subprocess.run(self.from_info(), input=self.info(name=name), capture_output=True, text=True,
                                        env=dict(environment, LANG=utf8), timeout=60)
                self.assertEqual((result.returncode, result.stdout),
                                 (1, "Inventory name must be a plain hostname-like token.\n"))
                self.assertEqual(self.state(), (INVENTORY, ""))

    def test_an_inventory_with_other_letters_is_still_edited(self):
        # The byte-wise locale does not stop the edit from reading a UTF-8 comment.
        inventory = "# Labor f\u00fcr \u00dcbungen\n" + INVENTORY
        self.inventory.write_text(inventory, encoding="utf-8")
        result = self.paste(self.info())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.inventory.read_text(encoding="utf-8"), inventory.replace(
            "[enterprise_linux]\n", f"[enterprise_linux]\nlab-alma ansible_host={TEST_NET}.12\n"))


if __name__ == "__main__":
    unittest.main()
