"""controller/onboard-target.sh, with ssh, scp and sudo simulated, and onboard-linux.sh's options."""

import os
import pty
import re
import select
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "controller" / "onboard-target.sh"
ONBOARD = ROOT / "onboard" / "existing" / "onboard-linux.sh"
BASH = shutil.which("bash") or "/bin/bash"
PASSWORD = "correct horse battery"
# A documentation network, assembled so that the repository holds no literal address.
NET = ".".join(("192", "0", "2"))
FIRST, SECOND, REPORTED = f"{NET}.13", f"{NET}.14", f"{NET}.99"
FINGERPRINT = "SHA256:" + "A" * 43

# What onboard-linux.sh prints at the end, as a terminal shows it.
REPORT = ("host: lab-alma (AlmaLinux 9.8)\r\npassword: set from PASSWORD_HASH\r\n"
          "Add this VM on the controller: in the guide's folder, run\r\n"
          "  sudo bash controller/add-target.sh --from-info\r\nthen paste these lines and press Ctrl-D:\r\n"
          f"name=lab-alma\r\naddress={REPORTED}\r\ngroup=enterprise_linux\r\nfingerprint={FINGERPRINT}\r\n")

FAKE_SSH = r'''#!/bin/bash
# Stands in for ssh: logs its arguments and plays the machine's part.
printf '%s\n' "$*" >> "$FAKE_LOG/ssh"
command=${!#}
case "$*" in
  *"-O exit"*) exit 0 ;;
esac
case "$command" in
  *"mktemp -d"*)
    [ -z "${FAKE_LOGIN_FAILS:-}" ] || exit 255
    if [ -n "${FAKE_REMOTE_DIR:-}" ]; then printf '%s\r\n' "$FAKE_REMOTE_DIR"; else mkdir -p "$FAKE_LOG/remote" && printf '%s\r\n' "$FAKE_LOG/remote"; fi ;;
  *onboard-linux.sh*)
    printf '%s' "$FAKE_REPORT"
    printf 'RESULT: %s\r\n' "${FAKE_RESULT:-OK}"
    [ "${FAKE_RESULT:-OK}" = OK ] || exit 1 ;;
  *"rm -rf"*) exit 0 ;;
  *) exit 0 ;;
esac
'''

FAKE_SCP = r'''#!/bin/bash
printf '%s\n' "$*" >> "$FAKE_LOG/scp"
[ -z "${FAKE_SCP_FAILS:-}" ] || exit 1
destination=${!#}
directory=${destination##*:}
for argument in "$@"; do
  [ -f "$argument" ] && cp -p -- "$argument" "$directory" || true
done
'''

FAKE_SSH_KEYGEN = r'''#!/bin/bash
# ssh-keygen reads the account's real known hosts, whatever HOME says: answer -F from the test's own list.
if [ "$1" = -F ]; then
  grep -q -x -F -- "$2" "$FAKE_LOG/known" 2>/dev/null
  exit
fi
exec "$REAL_SSH_KEYGEN" "$@"
'''

FAKE_SUDO = r'''#!/bin/bash
# sudo cat KEY prints the service key; sudo bash add-target.sh logs options and input.
if [ "$1" = cat ]; then
  [ -z "${FAKE_NO_KEY:-}" ] || exit 1
  cat "$FAKE_LOG/service-key.pub"
  exit 0
fi
printf '%s\n' "$*" >> "$FAKE_LOG/sudo"
cat >> "$FAKE_LOG/add-target-input"
printf -- '---\n' >> "$FAKE_LOG/add-target-input"
echo "Added by the simulated add-target.sh"
exit "${FAKE_ADD_STATUS:-0}"
'''


def run_in_terminal(arguments, env, typed=(), timeout=60):
    """Run a command with a pseudo-terminal as standard input, typing each line when asked."""
    controller, terminal = pty.openpty()
    process = subprocess.Popen(arguments, stdin=terminal, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                               start_new_session=True)
    os.close(terminal)
    for line in typed:
        os.write(controller, (line + "\n").encode())
    output, _ = process.communicate(timeout=timeout)
    # Drain what the terminal echoed, so closing it cannot block.
    while select.select([controller], [], [], 0)[0]:
        try:
            if not os.read(controller, 4096):
                break
        except OSError:
            break
    os.close(controller)
    return process.returncode, output.decode()


class OnboardTargetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        work = Path(self.directory.name)
        self.log, self.bin, self.home = work / "log", work / "bin", work / "home"
        for folder in (self.log, self.bin, self.home / ".ssh"):
            folder.mkdir(parents=True)
        for name, text in (("ssh", FAKE_SSH), ("scp", FAKE_SCP), ("sudo", FAKE_SUDO), ("ssh-keygen", FAKE_SSH_KEYGEN)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        subprocess.run(["ssh-keygen", "-q", "-t", "rsa", "-b", "2048", "-N", "", "-C", "ansible-guide",
                        "-f", str(work / "service-key")], check=True)
        shutil.copy(work / "service-key.pub", self.log / "service-key.pub")
        self.env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": str(self.home), "FAKE_LOG": str(self.log),
                    "FAKE_REPORT": REPORT, "REAL_SSH_KEYGEN": shutil.which("ssh-keygen")}

    def run_wrapper(self, *arguments, typed=None, **extra):
        env = {**self.env, **extra}
        command = [BASH, str(WRAPPER), *arguments]
        if typed is None:
            result = subprocess.run(command, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)
            return result.returncode, result.stdout + result.stderr
        return run_in_terminal(command, env, typed)

    def logged(self, name):
        path = self.log / name
        return path.read_text() if path.exists() else ""

    def test_one_machine_is_prepared_and_added_with_the_typed_address(self):
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password")
        self.assertEqual(status, 0, output)
        self.assertIn(f"Prepared and in the inventory: labadmin@{FIRST}", output)
        self.assertIn("sudo python3.12 controller/lab-sudo.py", output)
        # add-target.sh gets the machine's name, group and fingerprint as data, and the address typed here.
        self.assertEqual(self.logged("sudo").split()[-3:], ["--from-info", "--address", f"{FIRST}"])
        self.assertEqual(self.logged("add-target-input"),
                         f"name=lab-alma\ngroup=enterprise_linux\nfingerprint={FINGERPRINT}\n---\n")
        # The script, the key and nothing else were copied; the remote folder is removed afterwards.
        copied = self.logged("scp")
        self.assertIn("onboard-linux.sh", copied)
        self.assertIn("svc_ansible.pub", copied)
        self.assertNotIn("hash", copied)
        run = [line for line in self.logged("ssh").splitlines() if "onboard-linux.sh" in line][0]
        self.assertIn("sudo bash onboard-linux.sh --keys svc_ansible.pub --controller-address", run)
        self.assertIn('"${SSH_CONNECTION%% *}"', run)
        self.assertRegex(run, r"sh -c 'cleanup\(\) \{ cd / && rm -rf -- \S+/remote; \}; trap \"cleanup; exit 130\" HUP INT TERM; ")
        self.assertRegex(run, r"; status=\$\?; cleanup; exit \$status'$")
        self.assertIn(" -t ", " " + run)

    def sent_command(self):
        """What the wrapper asked the machine to run, after a run that left the copied files in place."""
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password")
        self.assertEqual(status, 0, output)
        run = [line for line in self.logged("ssh").splitlines() if "onboard-linux.sh" in line][0]
        return run[run.index("sh -c 'cleanup()"):]

    def machine(self, sudo_body):
        """A PATH whose sudo is a stand-in, and the environment sshd gives a command."""
        there = Path(self.directory.name) / "there"
        there.mkdir(exist_ok=True)
        (there / "sudo").write_text(f"#!/bin/sh\n{sudo_body}\n")
        (there / "sudo").chmod(0o755)
        return {"PATH": f"{there}:{os.environ['PATH']}", "SSH_CONNECTION": f"{NET}.1 50000 {FIRST} 22",
                "SEEN": str(self.log / "seen")}

    def test_the_command_sent_runs_as_written_in_a_real_shell(self):
        # sshd hands the command to the account's shell; the stand-in for ssh never did.
        command = self.sent_command()
        remote = self.log / "remote"
        for shell in filter(shutil.which, ("sh", "bash", "dash")):
            with self.subTest(shell=shell):
                remote.mkdir(exist_ok=True)
                (remote / "sudo-password.hash").write_text("left behind\n")
                env = self.machine('pwd > "$SEEN"; printf "%s\\n" "$@" >> "$SEEN"; exit 7')
                result = subprocess.run([shell, "-c", command], env=env, capture_output=True, text=True, timeout=30)
                # The script's own exit status comes back, it ran in the folder with its
                # options whole, and the folder is gone.
                self.assertEqual(result.returncode, 7, result.stderr)
                self.assertEqual(self.logged("seen").splitlines(), [
                    str(remote), "bash", "onboard-linux.sh", "--keys", "svc_ansible.pub",
                    "--controller-address", f"{NET}.1"])
                self.assertFalse(remote.exists())

    def test_ctrl_c_at_the_machines_sudo_prompt_still_removes_the_folder(self):
        command = self.sent_command()
        remote = self.log / "remote"
        for shell in filter(shutil.which, ("sh", "bash", "dash")):
            with self.subTest(shell=shell):
                remote.mkdir(exist_ok=True)
                (remote / "sudo-password.hash").write_text("left behind\n")
                (self.log / "seen").unlink(missing_ok=True)
                env = self.machine('echo waiting > "$SEEN"; exec sleep 30')
                # A new session, as under sshd, and Ctrl-C reaches the whole foreground group.
                process = subprocess.Popen([shell, "-c", command], env=env, start_new_session=True,
                                           preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    for _ in range(100):
                        if (self.log / "seen").exists():
                            break
                        time.sleep(0.05)
                    os.killpg(process.pid, signal.SIGINT)
                    # The account's shell runs the command: bash becomes it and reports 130;
                    # dash stays its parent and dies of the signal, and the command still
                    # cleans up behind it.
                    self.assertIn(process.wait(timeout=20), (130, -signal.SIGINT))
                    for _ in range(100):
                        if not remote.exists():
                            break
                        time.sleep(0.05)
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.assertFalse(remote.exists())

    def test_a_failed_run_asks_once_more_for_the_folder_to_be_removed(self):
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", FAKE_RESULT="FAILED: run as root")
        self.assertEqual(status, 1, output)
        last = self.logged("ssh").splitlines()[-2]
        self.assertIn("BatchMode=yes", last)
        self.assertRegex(last, r"sh -c 'rm -rf -- \S+/remote'$")

    def test_an_ipv6_address_is_copied_to_in_brackets(self):
        address = ":".join(("2001", "db8", "", "5"))
        status, output = self.run_wrapper(f"labadmin@{address}", "--keep-password")
        self.assertEqual(status, 0, output)
        self.assertRegex(self.logged("scp").splitlines()[-1], rf" labadmin@\[{address}\]:\S+/remote/$")
        self.assertTrue((self.log / "remote" / "onboard-linux.sh").exists())
        # ssh and add-target.sh take the address as typed.
        self.assertIn(f" labadmin@{address} ", self.logged("ssh"))
        self.assertEqual(self.logged("sudo").split()[-3:], ["--from-info", "--address", address])

    def test_an_unknown_host_is_asked_for_its_rsa_key_and_a_known_one_is_not(self):
        self.run_wrapper(f"labadmin@{FIRST}", "--keep-password")
        self.assertIn("HostKeyAlgorithms=rsa-sha2-512,rsa-sha2-256", self.logged("ssh"))
        (self.log / "ssh").unlink()
        (self.log / "known").write_text(f"{FIRST}\n")
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password")
        self.assertEqual(status, 0, output)
        self.assertNotIn("HostKeyAlgorithms", self.logged("ssh"))
        self.assertNotIn("has not connected", output)

    def test_name_replaces_the_machines_own_name(self):
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", "--name", "lab-rocky",
                                          "--lab-dir", "/srv/ansible-lab")
        self.assertEqual(status, 0, output)
        self.assertEqual(self.logged("sudo").split()[-7:],
                         ["--from-info", "--address", f"{FIRST}", "--name", "lab-rocky", "--lab-dir", "/srv/ansible-lab"])
        self.assertNotIn("name=", self.logged("add-target-input"))

    def test_the_password_is_asked_once_and_only_its_hash_travels(self):
        status, output = self.run_wrapper(f"labadmin@{FIRST}", f"ops@{SECOND}", typed=[PASSWORD, PASSWORD])
        self.assertEqual(status, 0, output)
        self.assertEqual(output.count("Sudo password for svc_ansible"), 1)
        stored = (self.log / "remote" / "sudo-password.hash")
        self.assertRegex(stored.read_text().strip(), r"^\$6\$[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}$")
        self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
        for name in ("ssh", "scp", "sudo", "add-target-input"):
            self.assertNotIn(PASSWORD, self.logged(name))
            self.assertNotIn("$6$", self.logged(name))
        self.assertNotIn(PASSWORD, output)
        runs = [line for line in self.logged("ssh").splitlines() if "onboard-linux.sh" in line]
        self.assertEqual(len(runs), 2)
        for run in runs:
            self.assertIn("--keys svc_ansible.pub --password-hash-file sudo-password.hash --controller-address", run)

    def test_extra_keys_are_authorized_beside_the_service_key(self):
        work = Path(self.directory.name)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "my own key", "-f", str(work / "mine")], check=True)
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", "--extra-key", str(work / "mine.pub"))
        self.assertEqual(status, 0, output)
        copied = (self.log / "remote" / "svc_ansible.pub").read_text().splitlines()
        self.assertEqual(copied, [(self.log / "service-key.pub").read_text().strip(), (work / "mine.pub").read_text().strip()])
        # A file without a final line break, or with CRLF, does not run into the next key.
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "second", "-f", str(work / "two")], check=True)
        mine, two = (work / "mine.pub").read_text().strip(), (work / "two.pub").read_text().strip()
        (work / "mine.pub").write_text(mine)
        (work / "two.pub").write_text(two + "\r\n\r\n")
        (self.log / "service-key.pub").write_text((self.log / "service-key.pub").read_text().strip())
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", "--extra-key", str(work / "mine.pub"),
                                          "--extra-key", str(work / "two.pub"))
        self.assertEqual(status, 0, output)
        self.assertEqual((self.log / "remote" / "svc_ansible.pub").read_text(),
                         "".join(line + "\n" for line in ((self.log / "service-key.pub").read_text(), mine, two)))
        for arguments, message in ((("--extra-key", str(work / "missing.pub")), "Cannot read the key file"),
                                   (("--extra-key", str(work / "mine")), "is a private key; give its .pub file."),
                                   (("--extra-key", str(self.log / "ssh")), "is not a public key ssh-keygen can read.")):
            with self.subTest(arguments=arguments):
                (self.log / "ssh").write_text("not a key\n")
                status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", *arguments)
                self.assertEqual(status, 1, output)
                self.assertIn(message, output)
                self.assertEqual(self.logged("ssh"), "not a key\n")

    def test_the_password_length_counts_characters(self):
        # Eleven two-byte characters are 22 bytes and still too short.
        status, output = self.run_wrapper(f"labadmin@{FIRST}", typed=["é" * 11, "é" * 11])
        self.assertEqual(status, 1, output)
        self.assertIn("fewer than 12 characters", output)
        self.assertEqual(self.logged("ssh"), "")

    def test_passwords_that_differ_or_are_short_change_nothing(self):
        for typed, reason in (([PASSWORD, PASSWORD + "x"], "The two entries differ"),
                              (["short", "short"], "fewer than 12 characters")):
            with self.subTest(reason=reason):
                status, output = self.run_wrapper(f"labadmin@{FIRST}", typed=typed)
                self.assertEqual(status, 1, output)
                self.assertIn(reason, output)
                self.assertEqual(self.logged("ssh"), "")

    def test_without_a_terminal_it_asks_for_keep_password(self):
        status, output = self.run_wrapper(f"labadmin@{FIRST}")
        self.assertEqual(status, 1)
        self.assertIn("Run it from a terminal to be asked for the sudo password, or pass --keep-password.", output)
        self.assertEqual(self.logged("ssh"), "")

    def test_a_failed_script_is_not_added(self):
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", FAKE_RESULT="FAILED: run as root")
        self.assertEqual(status, 1, output)
        self.assertIn(f"Not finished: labadmin@{FIRST}", output)
        self.assertEqual(self.logged("sudo"), "")

    def test_a_report_without_the_result_line_is_not_added(self):
        # The last line decides, whatever came before it.
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password",
                                          FAKE_REPORT=REPORT + "RESULT: OK\r\nsomething after it\r\n", FAKE_RESULT="FAILED: x")
        self.assertEqual(status, 1, output)
        self.assertEqual(self.logged("sudo"), "")

    def test_a_folder_name_that_is_not_one_stops_before_anything_is_copied(self):
        for answer in ("/tmp/x; touch /tmp/owned", "/tmp/a b", "$(id)", "relative/path", ""):
            with self.subTest(answer=answer):
                for name in ("ssh", "scp"):
                    (self.log / name).unlink(missing_ok=True)
                status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", FAKE_REMOTE_DIR=answer or " ")
                self.assertEqual(status, 1, output)
                self.assertIn("answered with something other than a folder name", output)
                self.assertEqual(self.logged("scp"), "")
                self.assertNotIn("onboard-linux.sh", self.logged("ssh"))

    def test_each_machine_is_reported_and_one_failure_fails_the_run(self):
        status, output = self.run_wrapper(f"labadmin@{FIRST}", f"labadmin@{SECOND}", "--keep-password", FAKE_ADD_STATUS="2")
        self.assertEqual(status, 1, output)
        self.assertIn("is prepared, but add-target.sh did not add it", output)
        self.assertIn(f"Not finished: labadmin@{FIRST} labadmin@{SECOND}", output)
        self.assertEqual(len(self.logged("sudo").splitlines()), 2)

    def test_a_login_or_copy_failure_moves_on_to_the_next_machine(self):
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", FAKE_LOGIN_FAILS="1")
        self.assertEqual((status, self.logged("scp")), (1, ""), output)
        self.assertIn(f"Could not log in to labadmin@{FIRST}.", output)
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", FAKE_SCP_FAILS="1")
        self.assertEqual(status, 1, output)
        self.assertIn(f"Could not copy the script to labadmin@{FIRST}.", output)
        self.assertEqual(self.logged("sudo"), "")

    def test_arguments_are_checked_before_anything_runs(self):
        cases = {
            (): "Usage: bash controller/onboard-target.sh",
            (f"labadmin@{FIRST}", f"ops@{SECOND}", "--name", "one"): "--name names one machine",
            (f"labadmin@{FIRST}", "--name", "bad name"): "The name must be a plain hostname-like token.",
            (f"lab admin@{FIRST}",): "Give each machine as ADMIN@ADDRESS",
            (f"labadmin@{FIRST};id",): "Give each machine as ADMIN@ADDRESS",
            (f"{FIRST}",): "Give each machine as ADMIN@ADDRESS",
            (f"svc_ansible@{FIRST}",): "not as svc_ansible",
            (f"labadmin@{FIRST}", "--bogus"): "Unknown option: --bogus",
            (f"labadmin@{FIRST}", "--name"): "--name needs a value.",
        }
        for arguments, message in cases.items():
            with self.subTest(arguments=arguments):
                status, output = self.run_wrapper(*arguments, "--keep-password")
                self.assertEqual(status, 2, output)
                self.assertIn(message, output)
                self.assertEqual(self.logged("ssh"), "")

    def test_it_refuses_to_run_as_root_or_without_the_service_key(self):
        (self.bin / "id").write_text("#!/bin/sh\necho 0\n")
        (self.bin / "id").chmod(0o755)
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password")
        self.assertEqual(status, 1)
        self.assertIn("Run it as your administrator account, without sudo", output)
        (self.bin / "id").unlink()
        status, output = self.run_wrapper(f"labadmin@{FIRST}", "--keep-password", FAKE_NO_KEY="1")
        self.assertEqual(status, 1)
        self.assertIn("Could not read /etc/semaphore/svc_ansible.pub.", output)
        self.assertEqual(self.logged("ssh"), "")


class OnboardLinuxOptionTests(unittest.TestCase):
    """The options of onboard-linux.sh, up to the point where it needs root."""

    def run_script(self, *arguments):
        return subprocess.run([BASH, str(ONBOARD), *arguments], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=60)

    def section(self, typed=None, **variables):
        """Run the part that reads the options' inputs, with fail() reporting instead of exiting the test."""
        text = ONBOARD.read_text()
        start, end = text.index("# --- Inputs given as options"), text.index("# --- Inputs, checked before anything changes")
        patterns = "".join(line + "\n" for line in text.splitlines() if line.startswith("hash_pattern="))
        script = ('set -euo pipefail\naccount=svc_ansible\nPUBLIC_KEYS=unset\nPASSWORD_HASH=\n'
                  'fail() { printf "FAILED: %s\\n" "$*"; exit 1; }\n'
                  + "".join(f"{name}={value!r}\n" for name, value in variables.items())
                  + "".join(f"{name}=\n" for name in ("keys_file", "hash_file", "ask_password") if name not in variables)
                  + text[start:end] + patterns
                  + 'printf "KEYS: %s\\n" "$PUBLIC_KEYS"\n[[ $PASSWORD_HASH =~ $hash_pattern ]] && echo "HASH: valid" || printf "HASH: %s\\n" "$PASSWORD_HASH"\n')
        if typed is None:
            result = subprocess.run([BASH, "-c", script], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
            return result.returncode, result.stdout + result.stderr
        return run_in_terminal([BASH, "-c", script], dict(os.environ), typed)

    def test_help_and_unknown_options(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage: sudo bash onboard-linux.sh [--keys FILE]", result.stdout)
        self.assertNotIn("RESULT:", result.stdout)
        for arguments, reason in ((("--bogus",), "unknown option --bogus"), (("--keys",), "--keys needs a value"),
                                  (("--password-hash-file", ""), "--password-hash-file needs a value")):
            with self.subTest(arguments=arguments):
                result = self.run_script(*arguments)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(result.stdout.splitlines()[-1].startswith(f"RESULT: FAILED: {reason}"), result.stdout)

    @unittest.skipIf(os.geteuid() == 0, "needs an unprivileged account")
    def test_the_hash_file_is_removed_even_when_the_run_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            stored = Path(directory) / "hash"
            stored.write_text("$6$salt$" + "a" * 86 + "\n")
            result = self.run_script("--password-hash-file", str(stored))
            self.assertEqual(result.stdout.splitlines()[-1], "RESULT: FAILED: run as root, for example with: sudo bash onboard-linux.sh")
            self.assertFalse(stored.exists())

    def test_keys_and_hash_come_from_their_files(self):
        with tempfile.TemporaryDirectory() as directory:
            keys, stored = Path(directory) / "keys.pub", Path(directory) / "hash"
            keys.write_text("ssh-rsa AAAAB3NzaC1yc2E= ansible-guide\n")
            stored.write_text("\n$6$salt$" + "a" * 86 + "\r\n")
            status, output = self.section(keys_file=str(keys), hash_file=str(stored))
            self.assertEqual((status, output), (0, "KEYS: ssh-rsa AAAAB3NzaC1yc2E= ansible-guide\nHASH: valid\n"))
            for variables, reason in (({"keys_file": str(keys) + ".missing"}, "cannot read the key file"),
                                      ({"hash_file": str(stored) + ".missing"}, "cannot read the hash file"),
                                      ({"hash_file": str(stored), "ask_password": "yes"}, "give the password one way")):
                with self.subTest(variables=variables):
                    status, output = self.section(**variables)
                    self.assertEqual(status, 1)
                    self.assertIn("FAILED: " + reason, output)
            stored.write_text("\n")
            self.assertIn("is empty", self.section(hash_file=str(stored))[1])

    def test_ask_password_needs_a_terminal(self):
        status, output = self.section(ask_password="yes")
        self.assertEqual(status, 1)
        self.assertIn("FAILED: --ask-password needs a terminal", output)

    @unittest.skipUnless(shutil.which("openssl"), "needs openssl")
    def test_ask_password_hashes_what_is_typed_twice(self):
        status, output = self.section(typed=[PASSWORD, PASSWORD], ask_password="yes")
        self.assertEqual(status, 0, output)
        self.assertIn("HASH: valid", output)
        self.assertNotIn(PASSWORD, output)
        for typed, reason in (([PASSWORD, "another password"], "the two entries differ"),
                              (["short", "short"], "fewer than 12 characters")):
            with self.subTest(reason=reason):
                status, output = self.section(typed=typed, ask_password="yes")
                self.assertEqual(status, 1, output)
                self.assertRegex(output, "FAILED: [^\n]*" + reason)


class InstallerKeyCopyTests(unittest.TestCase):
    def test_the_editor_writes_its_own_copy_of_the_public_key(self):
        common = (ROOT / "controller" / "controller-common.sh").read_text()
        # root never writes into the editor's home itself, where a link could wait for it.
        self.assertRegex(common, r'runuser -u "\$editor" -- /bin/sh -c \'umask 022 && cat > "\$1"\' _ "\$editor_home/svc_ansible\.pub"')
        self.assertNotRegex(common, r'(install|cp)\b[^\n]*"\$editor_home')
        self.assertIn("bash controller/onboard-target.sh ADMIN@ADDRESS", common)
        self.assertTrue(re.search(r"a copy is in \$key_copy", common))


if __name__ == "__main__":
    unittest.main()
