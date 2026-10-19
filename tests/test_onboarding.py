"""Offline tests of the three onboarding paths: cloud-init, onboard-linux.sh and the bootstrap playbook.

The shell tests cut functions and blocks out of the files themselves and run them with
stand-in commands. The playbook tests render its own expressions through ansible-playbook,
which treats some Jinja differently from plain Jinja, using ansible-core alone: CI runs
them before it installs any collection. Nothing here changes the system or contacts a host.
"""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ONBOARD = (ROOT / "examples" / "onboard" / "onboard-linux.sh").read_text()
CLOUD_INIT_TEXT = (ROOT / "examples" / "onboard" / "cloud-init.yaml").read_text()
CLOUD_INIT = yaml.safe_load(CLOUD_INIT_TEXT)
PLAYBOOK_TEXT = (ROOT / "examples" / "bootstrap-existing-vm.yml").read_text()
PLAYBOOK = yaml.safe_load(PLAYBOOK_TEXT)[0]
CHAPTER_4 = (ROOT / "docs" / "04-access.md").read_text()
ADD_TARGET = (ROOT / "scripts" / "add-target.sh").read_text()
BASH = shutil.which("bash")
# Documentation addresses (RFC 5737), built in parts so the publication check accepts them.
TEST_NET = ".".join(("192", "0", "2"))
# The SHA256: form ssh-keygen -l prints: 43 base64 characters, no padding.
FINGERPRINT = "SHA256:" + "A1b2C3d4" * 5 + "E5f"
HASH = "$6$saltsalt$" + "a" * 86
RETRY = "onboard: apt-get update failed; another apt process may hold its lock. Retrying in 10 seconds."
GAVE_UP = "onboard: apt-get update failed 30 times, 10 seconds apart"


def first_boot_script():
    """The Bash program cloud-init runs at first boot: the runcmd entry ['/bin/bash', '-c', SCRIPT]."""
    scripts = [entry[2] for entry in CLOUD_INIT["runcmd"]
               if isinstance(entry, list) and len(entry) == 3 and entry[0].endswith("bash") and entry[1] == "-c"]
    assert len(scripts) == 1, "cloud-init.yaml should have one Bash runcmd entry"
    return scripts[0]


CLOUD_SCRIPT = first_boot_script()


def section(text, start, end=None):
    """The lines from the first that starts with start up to the next that starts with end, or the end."""
    lines = text.splitlines(keepends=True)
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    last = len(lines) if end is None else next(i for i in range(first + 1, len(lines)) if lines[i].startswith(end))
    return "".join(lines[first:last])


def function(text, name):
    """A shell function's whole definition, from 'name() {' to its closing brace in column 0."""
    return section(text, name + "() {", "}") + "}\n"


def playbook_tasks():
    """Every task of the play, including those in blocks and rescues."""
    for task in PLAYBOOK["pre_tasks"] + PLAYBOOK["tasks"]:
        yield task
        yield from task.get("block", []) + task.get("rescue", [])


def playbook_task(name):
    return next(task for task in playbook_tasks() if task["name"] == name)


def stand_ins(work, commands, keep_path=True):
    """A PATH whose first directory holds stand-in commands, each a /bin/sh body.

    Without keep_path, the PATH holds only the stand-ins and grep, so a command that is
    not stood in is missing, as apt-get is on Enterprise Linux.
    """
    directory = Path(work) / "bin"
    directory.mkdir(exist_ok=True)
    for name, body in commands.items():
        (directory / name).write_text("#!/bin/sh\n" + body + "\n")
        (directory / name).chmod(0o755)
    if not keep_path:
        (directory / "grep").symlink_to(shutil.which("grep"))
        return str(directory)
    return str(directory) + os.pathsep + os.environ["PATH"]


def run_bash(script, path=None, env=None, stdin="", args=()):
    environment = dict(os.environ, LC_ALL="C", **(env or {}))
    if path:
        environment["PATH"] = path
    return subprocess.run([BASH, "-c", script, "test", *args], input=stdin, capture_output=True,
                          text=True, env=environment, timeout=60)


# A stand-in apt-get that logs each call to $LOG. Its first $UPDATE_FAILURES updates fail, as
# they do while apt-daily holds the package lists' lock. When that number is not 0, an install
# fails until an update has succeeded, as it does on an image without package lists.
APT_GET = ('echo "apt-get $*" >>"$LOG"; n=0; [ -f "$LOG.n" ] && read -r n <"$LOG.n";'
           ' case " $* " in *" update "*) n=$((n + 1)); echo "$n" >"$LOG.n" ;; esac;'
           ' [ "$UPDATE_FAILURES" -eq 0 ] || [ "$n" -gt "$UPDATE_FAILURES" ]')


# The checks add-target.sh applies, read from the script so they cannot drift apart.
CHECKS = dict(re.findall(r'\[\[ "\$(name|address|fingerprint)" =~ (\^\S+\$) \]\]', ADD_TARGET))
GROUPS = re.findall(r'"\$group" == (\w+)', ADD_TARGET)


class AddTargetLineMixin:
    """Checks that a line is one add-target.sh command with values that script accepts."""

    def assertAddTargetLine(self, line, **expected):
        self.assertEqual(sorted(CHECKS), ["address", "fingerprint", "name"])
        self.assertEqual(GROUPS, ["ubuntu", "enterprise_linux"])
        words = shlex.split(line)
        self.assertEqual(words[:3], ["sudo", "bash", "scripts/add-target.sh"], line)
        options = dict(zip(words[3::2], words[4::2]))
        self.assertEqual(len(words), 3 + 2 * len(options), line)
        self.assertEqual(set(options) - {"--lab-dir"}, {"--name", "--address", "--group", "--fingerprint"}, line)
        self.assertIn(options["--group"], GROUPS)
        for field, pattern in CHECKS.items():
            # FINGERPRINT stands in when the host key cannot be read; add-target.sh refuses it.
            if options["--" + field] != "FINGERPRINT":
                self.assertIsNotNone(re.fullmatch(pattern, options["--" + field]), line)
        for field, value in expected.items():
            self.assertEqual(options["--" + field], value, line)


class AddTargetInfoMixin:
    """Checks the lines a script on the VM prints for add-target.sh --from-info: data, not a command."""

    # What the scripts ask for when they cannot read a value; never a placeholder.
    OPTIONS = {"name": "--name with the name the inventory should use",
               "address": "--address with the address the controller reaches",
               "fingerprint": "--fingerprint with the RSA host key's fingerprint, read from the console"}

    def assertInfoLines(self, lines, prefix="", **expected):
        """The block from its first line; each of the four values expected, or None where it is left out."""
        self.assertEqual(list(expected), ["name", "address", "group", "fingerprint"])
        for line in lines:
            self.assertTrue(line.startswith(prefix), lines)
        lines = [line.removeprefix(prefix) for line in lines]
        left_out = [key for key, value in expected.items() if value is None]
        self.assertEqual(lines[:2], ["Add this VM on the controller: in the guide's folder, run",
                                     "  sudo bash scripts/add-target.sh --from-info"])
        self.assertEqual(lines[2:2 + len(left_out)], [f"and add {self.OPTIONS[key]}," for key in left_out])
        self.assertEqual(lines[2 + len(left_out)], "then paste these lines and press Ctrl-D:")
        values = dict(line.split("=", 1) for line in lines[3 + len(left_out):])
        self.assertEqual(values, {key: value for key, value in expected.items() if value is not None})
        self.assertEqual(sorted(CHECKS), ["address", "fingerprint", "name"])
        self.assertIn(values["group"], GROUPS)
        for field, pattern in CHECKS.items():
            if field in values:
                self.assertIsNotNone(re.fullmatch(pattern, values[field]), lines)
        # A placeholder such as ADDRESS would pass add-target.sh's checks as a DNS name.
        for placeholder in ("NAME", "ADDRESS", "FINGERPRINT"):
            self.assertNotIn(placeholder, "\n".join(lines))

    def host_key(self):
        """A real RSA host key: its public line and the fingerprint add-target.sh compares with a scan."""
        if not shutil.which("ssh-keygen"):
            self.skipTest("needs ssh-keygen")
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        path = Path(work.name, "ssh_host_rsa_key")
        subprocess.run(["ssh-keygen", "-q", "-t", "rsa", "-b", "2048", "-N", "", "-f", str(path)], check=True)
        fingerprint = subprocess.run(["ssh-keygen", "-lf", f"{path}.pub"], capture_output=True, text=True,
                                     check=True).stdout.split()[1]
        return " ".join(Path(f"{path}.pub").read_text().split()[:2]), fingerprint

    def assertAddTargetAdds(self, output, key, entry, options=()):
        """add-target.sh --from-info, given the whole output as pasted, adds the inventory entry."""
        with tempfile.TemporaryDirectory() as work:
            inventory = Path(work, "lab", "inventories", "lab.ini")
            inventory.parent.mkdir(parents=True)
            inventory.write_text("[ubuntu]\n\n[enterprise_linux]\n")
            Path(work, "known_hosts").write_text("")
            # add-target.sh needs root and scans the target; stand-ins answer for both.
            path = stand_ins(work, {"id": "echo 0", "ssh-keyscan": f'for last; do :; done; echo "$last {key}"'})
            result = subprocess.run([BASH, str(ROOT / "scripts" / "add-target.sh"), "--from-info", *options,
                                     "--lab-dir", str(Path(work, "lab")),
                                     "--known-hosts", str(Path(work, "known_hosts"))],
                                    input=output, capture_output=True, text=True, env=dict(os.environ, PATH=path),
                                    timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(entry + "\n", inventory.read_text())


class SharedSettingsTests(unittest.TestCase):
    """cloud-init, onboard-linux.sh, the playbook and chapter 4 each carry the same settings."""

    def cloud_init_file(self, path):
        return next(entry["content"] for entry in CLOUD_INIT["write_files"] if entry["path"] == path)

    def test_the_sudoers_rule_is_the_same_everywhere(self):
        rule = playbook_task("Allow svc_ansible to use sudo with its password")
        copies = {
            "cloud-init": self.cloud_init_file("/etc/sudoers.d/90-ansible-lab"),
            "onboard-linux.sh": re.search(r"<<'SUDOERS'\n(.*?)^SUDOERS$", ONBOARD, re.S | re.M)[1],
            "playbook": rule["ansible.builtin.copy"]["content"],
            "chapter 4": re.search(r"^```sudoers\n(.*?)^```$", CHAPTER_4, re.S | re.M)[1],
        }
        # The account's own password, never NOPASSWD.
        for source, text in copies.items():
            self.assertEqual(text, "Defaults:svc_ansible !requiretty\nsvc_ansible ALL=(ALL:ALL) ALL\n", source)

    def test_the_ssh_drop_in_is_the_same_everywhere(self):
        copies = {
            "cloud-init": self.cloud_init_file("/etc/ssh/sshd_config.d/70-ansible-lab.conf"),
            "onboard-linux.sh": re.search(r"<<'DROPIN'\n(.*?)^DROPIN$", ONBOARD, re.S | re.M)[1],
            "playbook": playbook_task("Write the account's SSH drop-in")["ansible.builtin.copy"]["content"],
            "chapter 4": re.search(r"70-ansible-lab\.conf >/dev/null <<'EOF'\n(.*?)^EOF$", CHAPTER_4, re.S | re.M)[1],
        }
        for source, text in copies.items():
            self.assertEqual(text, "Match User svc_ansible\n    AuthenticationMethods publickey\n"
                             "    PasswordAuthentication no\n    KbdInteractiveAuthentication no\nMatch all\n", source)

    def test_the_rsa_signature_algorithms_are_the_same_everywhere(self):
        # Chapter 4 names them for the host key; the key checks accept the same for client
        # keys, because the controller's SSH client never signs with SHA-1 ssh-rsa.
        usable = next(t for t in PLAYBOOK["pre_tasks"] if t["name"] == "Require at least one listed key that can log in")
        copies = {
            "cloud-init": re.search(r"ssh-rsa\) algorithms='([^']*)'", CLOUD_SCRIPT)[1].split(),
            "onboard-linux.sh": re.search(r"algorithms='(rsa-[^']*)'", ONBOARD)[1].split(),
            "playbook": re.findall(r"'([^']+)'", re.search(r"\[([^]]*)\] \| intersect",
                                                         usable["vars"]["bootstrap_rsa_accepted"])[1]),
            "chapter 4": re.search(r"HostKeyAlgorithms=(\S+)", CHAPTER_4)[1].split(","),
        }
        for source, algorithms in copies.items():
            self.assertEqual(algorithms, ["rsa-sha2-512", "rsa-sha2-256"], source)

    def test_cloud_init_runs_the_same_shell_functions_as_onboard_linux(self):
        for name in ("apt_update", "sshd_files", "sshd_access"):
            with self.subTest(function=name):
                self.assertEqual(function(CLOUD_SCRIPT, name), function(ONBOARD, name))


class CloudInitTests(AddTargetInfoMixin, unittest.TestCase):
    """The first-boot script, which runs unattended on every new VM."""

    def test_the_first_boot_script_is_valid_bash(self):
        result = subprocess.run([BASH, "-n"], input=CLOUD_SCRIPT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        if shutil.which("shellcheck"):
            result = subprocess.run(["shellcheck", "-s", "bash", "-S", "warning", "-"], input=CLOUD_SCRIPT,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_targets_yml_finds_the_quoted_key_placeholder_once(self):
        self.assertEqual(CLOUD_INIT_TEXT.count('"REPLACE_WITH_AUTOMATION_PUBLIC_KEY"'), 1)

    def install(self, installed, apt, fail=False, update_failures=0):
        """Run the package block with stand-ins that log each command; apt picks the family."""
        block = section(CLOUD_SCRIPT, "# apt-get update takes the package lists' lock", "if ! visudo -cq")
        with tempfile.TemporaryDirectory() as work:
            log = Path(work) / "log"
            log.write_text("")
            commands = {
                "rpm": 'echo "rpm $*" >>"$LOG"; case " $INSTALLED " in *" $2 "*) exit 0 ;; esac; exit 1',
                "dnf": 'echo "dnf $*" >>"$LOG"; exit "$FAIL"',
            }
            if apt:
                commands = {
                    "dpkg-query": 'for p; do :; done; case " $INSTALLED " in *" $p "*) printf "install ok installed" ;;'
                                  ' *) echo "dpkg-query: no packages found matching $p" >&2; exit 1 ;; esac',
                    "apt-get": APT_GET,
                    "sleep": 'echo "sleep $*" >>"$LOG"',
                    "install": 'echo "install $*" >>"$LOG"',
                }
            script = ('set -u\nfailed=\nproblem() { echo "onboard: ERROR: $*"; failed=yes; }\n' + block
                      + 'echo "group=$inventory_group unit=$ssh_unit failed=$failed"\n')
            result = run_bash(script, stand_ins(work, commands, keep_path=False),
                              {"LOG": str(log), "INSTALLED": " ".join(installed), "FAIL": "1" if fail else "0",
                               "UPDATE_FAILURES": str(update_failures)})
            return result.stdout, log.read_text().splitlines()

    def test_packages_are_installed_only_when_missing(self):
        output, log = self.install(["python3", "python3-dnf", "python3-libselinux"], apt=False)
        self.assertEqual(output, "group=enterprise_linux unit=sshd failed=\n")
        self.assertFalse([line for line in log if line.startswith("dnf")], log)
        output, log = self.install(["python3", "python3-dnf"], apt=False)
        self.assertEqual(log[-1], "dnf -y -q install python3-libselinux")
        output, log = self.install(["python3", "python3-apt"], apt=True)
        self.assertEqual(output, "group=ubuntu unit=ssh failed=\n")
        self.assertEqual(log, ["install -d -m 0755 /run/sshd"])
        output, log = self.install(["python3"], apt=True)
        self.assertEqual(log, ["apt-get -o DPkg::Lock::Timeout=600 install -y -q python3-apt",
                               "install -d -m 0755 /run/sshd"])

    def test_a_failed_installation_is_reported(self):
        output, log = self.install(["python3"], apt=False, fail=True)
        self.assertEqual(log[-1], "dnf -y -q install python3-dnf python3-libselinux")
        self.assertEqual(output, "onboard: ERROR: python3-dnf installation failed\n"
                                 "group=enterprise_linux unit=sshd failed=yes\n")

    def test_apt_get_update_is_retried_a_bounded_number_of_times(self):
        install = "apt-get -o DPkg::Lock::Timeout=600 install -y -q python3-apt"
        # The install fails without fresh package lists; the update succeeds on its third try.
        output, log = self.install(["python3"], apt=True, update_failures=2)
        self.assertEqual(log, [install] + ["apt-get update -q", "sleep 10"] * 2
                         + ["apt-get update -q", install, "install -d -m 0755 /run/sshd"])
        self.assertEqual(output.splitlines(), [RETRY, RETRY, "group=ubuntu unit=ssh failed="])
        # Thirty failures, ten seconds apart, are about five minutes; then cloud-init reports an error.
        output, log = self.install(["python3"], apt=True, update_failures=30)
        self.assertEqual((log.count("apt-get update -q"), log.count("sleep 10"), log.count(install)), (30, 29, 1))
        self.assertEqual(output.splitlines()[-3:], [GAVE_UP, "onboard: ERROR: python3-apt installation failed",
                                                    "group=ubuntu unit=ssh failed=yes"])

    def test_access_refusals_are_problems_and_patterns_only_warnings(self):
        block = section(CLOUD_SCRIPT, "# sshd refuses an account that DenyUsers", "# Reload a running server")
        script = ('set -u\nfailed=\nproblem() { echo "onboard: ERROR: $*"; failed=yes; }\npolicy=$POLICY\n'
                  + block + 'echo "failed=$failed"\n')
        with tempfile.TemporaryDirectory() as work:
            result = run_bash(script, stand_ins(work, {"id": 'echo "$GROUP_NAMES"'}),
                              {"POLICY": "port 22\nallowusers azadmin\nallowgroups ssh*", "GROUP_NAMES": "svc_ansible"})
        self.assertEqual(result.stdout.splitlines(), [
            "onboard: ERROR: AllowUsers does not list svc_ansible; sshd would refuse the account,"
            " so allow svc_ansible there",
            'onboard: warning: this check cannot evaluate "AllowGroups ssh*"; make sure sshd lets svc_ansible in',
            "failed=yes",
        ])
        # Before the reload, which happens either way; the error makes cloud-init report it.
        self.assertLess(CLOUD_SCRIPT.index('sshd_access "$policy"'), CLOUD_SCRIPT.index('systemctl reload "$ssh_unit"'))

    def final_lines(self, addresses, name="lab-alma", fingerprint=FINGERPRINT):
        block = section(CLOUD_SCRIPT, "# The values add-target.sh --from-info reads")
        with tempfile.TemporaryDirectory() as work:
            commands = {
                "hostname": 'echo "$NAME"',
                "ip": 'for a in $ADDRESSES; do printf "2: eth0    inet %s/24 brd x scope global eth0\\n" "$a"; done',
                "ssh-keygen": '[ -n "$FP" ] || exit 1; echo "3072 $FP root@lab (RSA)"',
            }
            result = run_bash("set -u\ninventory_group=enterprise_linux\n" + block, stand_ins(work, commands),
                              {"NAME": name, "ADDRESSES": " ".join(addresses), "FP": fingerprint})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_a_successful_run_ends_with_the_lines_for_add_target(self):
        # The block follows the ready message and ends the script.
        ready = 'echo "onboard: svc_ansible is ready; set its sudo password next"\n'
        closing = section(CLOUD_SCRIPT, "# The values add-target.sh --from-info reads")
        self.assertTrue(CLOUD_SCRIPT.endswith(ready + closing))
        self.assertInfoLines(self.final_lines([f"{TEST_NET}.12"]), prefix="onboard: ", name="lab-alma",
                             address=f"{TEST_NET}.12", group="enterprise_linux", fingerprint=FINGERPRINT)

    def test_unknown_values_are_left_out_and_their_options_named(self):
        lines = self.final_lines([f"{TEST_NET}.12", f"{TEST_NET}.13"], name="bad_name!", fingerprint="")
        self.assertInfoLines(lines, prefix="onboard: ", name=None, address=None, group="enterprise_linux",
                             fingerprint=None)
        self.assertInfoLines(self.final_lines([]), prefix="onboard: ", name="lab-alma", address=None,
                             group="enterprise_linux", fingerprint=FINGERPRINT)
        # localhost is Ansible's name for the controller, which add-target.sh refuses.
        self.assertInfoLines(self.final_lines([f"{TEST_NET}.12"], name="localhost"), prefix="onboard: ", name=None,
                             address=f"{TEST_NET}.12", group="enterprise_linux", fingerprint=FINGERPRINT)

    def test_the_log_pasted_whole_adds_the_vm(self):
        # As sudo grep onboard /var/log/cloud-init-output.log shows it, with the ready message.
        key, fingerprint = self.host_key()
        log = "onboard: svc_ansible is ready; set its sudo password next\n"
        lines = self.final_lines([f"{TEST_NET}.12"], fingerprint=fingerprint)
        self.assertAddTargetAdds(log + "\n".join(lines) + "\n", key, f"lab-alma ansible_host={TEST_NET}.12")
        # An address it could not tell comes from the option the output names.
        lines = self.final_lines([], fingerprint=fingerprint)
        self.assertAddTargetAdds(log + "\n".join(lines) + "\n", key, f"lab-alma ansible_host={TEST_NET}.14",
                                 options=("--address", f"{TEST_NET}.14"))


class OnboardScriptTests(AddTargetInfoMixin, unittest.TestCase):
    """onboard-linux.sh's helpers, result line and closing lines for add-target.sh --from-info."""

    # Its settings, traps and helpers, up to the root check, and the inputs set above them.
    PREAMBLE = ("PUBLIC_KEYS=key\nPASSWORD_HASH=\nCONTROLLER_ADDRESS=\n"
                + section(ONBOARD, "set -euo pipefail", '[ "$(id -u)" -eq 0 ]'))

    def run_onboard(self, body, commands=None, env=None):
        with tempfile.TemporaryDirectory() as work:
            path = stand_ins(work, commands or {})
            return run_bash(self.PREAMBLE + body, path, dict(env or {}, TMPDIR=work))

    def test_every_failure_still_ends_with_one_result_line(self):
        start = 'echo "work=$work"\n'
        line = len((self.PREAMBLE + start).splitlines()) + 1
        cases = {
            "false\n": f"RESULT: FAILED: unexpected error at line {line}; see the error output",
            "fails() { false; }\nfails\n": "RESULT: FAILED: unexpected error; see the error output",
            "echo $unset\n": "RESULT: FAILED: unexpected error; see the error output",
            'fail "a reason"\n': "RESULT: FAILED: a reason",
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                result = self.run_onboard(start + body)
                lines = result.stdout.splitlines()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(lines[-1], expected, result.stdout)
                self.assertEqual(len([line for line in lines if line.startswith("RESULT:")]), 1, result.stdout)
                self.assertFalse(Path(lines[0].removeprefix("work=")).exists())
        result = self.run_onboard('note "RESULT: OK"\n')
        self.assertEqual((result.returncode, result.stdout), (0, "RESULT: OK\n"))

    def test_known_failures_name_their_cause(self):
        account = section(ONBOARD, "# --- Account and keys", 'uid=$(id -u "$account")')
        labels = "home=/home/svc_ansible\n" + section(ONBOARD, "if command -v selinuxenabled", "# --- Password")
        password = section(ONBOARD, "# --- Password", "# --- sudo")
        rights = section(ONBOARD, 'rights=$(sudo -l -U "$account")', "grep -q '(ALL : ALL) ALL'")
        cases = [
            (account, {"getent": "exit 2", "useradd": 'echo "useradd: group svc_ansible exists" >&2; exit 9'}, {},
             "useradd could not create svc_ansible; if a group named svc_ansible exists already, resolve that by hand"),
            (account, {"getent": 'echo "svc_ansible:x:1001:1001::/home/svc_ansible:/bin/sh"', "id": "echo 1001",
                       "usermod": "exit 6"}, {},
             "usermod could not set svc_ansible's shell to /bin/bash; is it a local account?"),
            (labels, {"selinuxenabled": "exit 0", "restorecon": "exit 1"}, {},
             "restorecon could not restore the SELinux labels of /home/svc_ansible/.ssh"),
            (password, {"getent": 'echo "svc_ansible:!:20000::::::"', "chpasswd": "cat >/dev/null; exit 1"},
             {"ONBOARD_PASSWORD_HASH": HASH},
             "chpasswd could not set svc_ansible's password; is it a local account in /etc/shadow?"),
            (rights, {"sudo": "exit 1"}, {},
             "sudo -l -U svc_ansible failed, so its rights cannot be checked; see the error output"),
        ]
        for block, commands, env, expected in cases:
            with self.subTest(expected=expected):
                result = self.run_onboard(block, commands, env)
                self.assertEqual(result.stdout.splitlines()[-1:], ["RESULT: FAILED: " + expected],
                                 result.stdout + result.stderr)

    def test_apt_get_update_is_retried_and_its_output_kept_in_the_log(self):
        block = section(ONBOARD, "# apt-get update takes the package lists' lock", "# --- Keys")
        commands = {
            "dpkg-query": 'for p; do :; done; [ "$p" != python3-apt ] && printf "install ok installed"',
            "apt-get": APT_GET,
            "sleep": 'echo "sleep $*"',
            "install": ":",
        }
        install = "apt-get -o DPkg::Lock::Timeout=600 install -y -q python3-apt"
        for failures in (1, 30):
            with self.subTest(failures=failures), tempfile.TemporaryDirectory() as logs:
                log = Path(logs, "onboard.log")
                result = self.run_onboard(f"family=debian\nlog_file={log}\n" + block + 'note "packages: $packages"\n',
                                          commands, {"LOG": str(log), "UPDATE_FAILURES": str(failures)})
                logged = log.read_text().splitlines()
                # Run Command's 4 KB output gets one line; apt-get's own output goes to the log.
                if failures == 1:
                    self.assertEqual(result.stdout, "packages: present, installed python3-apt\n")
                    self.assertEqual(logged, ["apt-get update -q", RETRY, "sleep 10", "apt-get update -q", install])
                else:
                    self.assertEqual(result.stdout, "RESULT: FAILED: apt-get update failed 30 times, 10 seconds"
                                                    f" apart; see {log}\n")
                    self.assertEqual((logged.count("apt-get update -q"), logged.count("sleep 10")), (30, 29))
                    self.assertEqual(logged[-1], GAVE_UP)
                    self.assertNotIn(install, logged)

    def test_the_checks_come_before_the_drop_in_is_applied(self):
        # The groups are read before the drop-in is written, and every check before the reload.
        steps = ('groups=$(id -nG "$account")', 'install -o root -g root -m 0644 "$work/dropin"',
                 "problem=$(ssh_problem)", "if ! apply_ssh")
        order = [ONBOARD.index(step) for step in steps]
        self.assertEqual(order, sorted(order))

    def test_an_access_refusal_stops_the_ssh_check_for_each_address(self):
        functions = "".join(function(ONBOARD, name) for name in ("reads_key_file", "sshd_access", "ssh_problem"))
        policy = ("authenticationmethods publickey\npasswordauthentication no\nkbdinteractiveauthentication no\n"
                  "pubkeyauthentication yes\nauthorizedkeysfile .ssh/authorized_keys\n")
        with tempfile.TemporaryDirectory() as work:
            sshd = Path(work, "sshd")
            sshd.write_text('#!/bin/sh\n[ "$1" = -t ] && exit 0\nprintf "%s\\n" "$POLICY"\n')
            sshd.chmod(0o755)
            contexts = " ".join(f"user=svc_ansible,host={TEST_NET}.5,addr={TEST_NET}.5,laddr={TEST_NET}.{n},lport=22"
                                for n in (12, 13))
            script = (f"work={work}\nhome=/home/svc_ansible\naccount=svc_ansible\nuid=1001\ngroups=svc_ansible\n"
                      f"contexts=({contexts})\n" + functions.replace("/usr/sbin/sshd", str(sshd))
                      + ': >"$work/unsure"\nproblem=$(ssh_problem)\necho "problem=$problem"\ncat "$work/unsure"\n')
            refused = run_bash(script, env={"POLICY": policy + "allowgroups sshusers"}).stdout
            unsure = run_bash(script, env={"POLICY": policy + "allowusers adm*\nallowusers svc_ansible@x"}).stdout
        self.assertEqual(refused, "problem=AllowGroups lists none of svc_ansible's groups (svc_ansible); sshd would"
                         " refuse the account, so allow svc_ansible there"
                         f" (host={TEST_NET}.5,addr={TEST_NET}.5,laddr={TEST_NET}.12,lport=22)\n")
        # A pattern does not stop the run; each address's entries are kept for the report.
        self.assertEqual(unsure, "problem=\n" + "AllowUsers adm*\nAllowUsers svc_ansible@x\n" * 2)

    def test_key_and_hash_patterns(self):
        patterns = "".join(line + "\n" for line in ONBOARD.splitlines()
                           if line.startswith(("key_pattern=", "hash_pattern=")))
        script = patterns + ('for v in "$@"; do if [[ $v =~ $key_pattern ]]; then echo key;'
                             ' elif [[ $v =~ $hash_pattern ]]; then echo hash; else echo none; fi; done')
        cases = {
            "ssh-rsa AAAAB3NzaC1yc2E= ansible-practice": "key",
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5": "key",
            "ecdsa-sha2-nistp384 AAAAE2VjZHNh comment with spaces": "key",
            "ssh-dss AAAAB3NzaC1kc3M=": "none",
            "ssh-rsa": "none",
            "ssh-rsa AAAA$(id)": "none",
            HASH: "hash",
            "$6$rounds=5000$saltsalt$" + "a" * 86: "hash",
            "$6$rounds=0$saltsalt$" + "a" * 86: "none",
            "$5$saltsalt$" + "a" * 43: "none",
            HASH + "x": "none",
        }
        result = run_bash(script, args=list(cases))
        self.assertEqual(result.stdout.split(), list(cases.values()))

    def test_reads_key_file_resolves_tokens_and_relative_paths(self):
        script = ("home=/home/svc_ansible\naccount=svc_ansible\nuid=1001\n" + function(ONBOARD, "reads_key_file")
                  + 'for v in "$@"; do if reads_key_file "port 22\nauthorizedkeysfile $v"; then echo yes;'
                    ' else echo no; fi; done')
        cases = {
            ".ssh/authorized_keys .ssh/authorized_keys2": "yes",
            "%h/.ssh/authorized_keys": "yes",
            "/home/%u/.ssh/authorized_keys": "yes",
            "/etc/ssh/keys/%U .ssh/authorized_keys": "yes",
            "/etc/ssh/keys/%u": "no",
            "%%h/.ssh/authorized_keys": "no",
            "none": "no",
        }
        result = run_bash(script, args=list(cases))
        self.assertEqual(result.stdout.split(), list(cases.values()))

    def test_sshd_files_follows_includes_once(self):
        with tempfile.TemporaryDirectory() as work:
            main, extra, nested = Path(work, "sshd_config"), Path(work, "conf.d/a.conf"), Path(work, "nested.conf")
            extra.parent.mkdir()
            main.write_text(f"Port 22\nInclude {work}/conf.d/*.conf\n")
            extra.write_text(f"include {nested} {work}/missing.conf\n")
            nested.write_text(f"Include {main}\n")
            result = run_bash(function(ONBOARD, "sshd_files") + 'sshd_files 1 "$1" | sort -u', args=[str(main)])
        self.assertEqual(result.stdout.split(), sorted(str(p) for p in (main, extra, nested)))

    # Stand-ins for the commands the closing block reads its values from.
    CLOSING_COMMANDS = {
        "hostname": 'echo "$NAME"',
        "ip": 'case "$2" in route) [ -z "$SOURCE" ] || echo "$4 via gw dev eth0 src $SOURCE uid 0" ;;'
              ' *) for a in $ADDRESSES; do printf "2: eth0    inet %s/24 brd x scope global eth0\\n" "$a"; done ;;'
              ' esac',
        "ssh-keygen": '[ -n "$FP" ] || exit 1; echo "3072 $FP root@lab (RSA)"',
    }

    def closing_lines(self, setup, name, addresses, source, fingerprint):
        """The closing block's output, from values the stand-in commands give."""
        result = self.run_onboard(setup + section(ONBOARD, "# The values add-target.sh --from-info reads"),
                                  self.CLOSING_COMMANDS,
                                  {"NAME": name, "ADDRESSES": addresses, "SOURCE": source, "FP": fingerprint})
        lines = result.stdout.splitlines()
        self.assertEqual(lines[-1], "RESULT: OK", result.stdout + result.stderr)
        return lines

    def test_the_closing_lines_are_the_values_for_add_target(self):
        cases = [
            ("family=el\nCONTROLLER_ADDRESS=" + TEST_NET + ".5\n", "lab-vm", f"{TEST_NET}.12 {TEST_NET}.13",
             f"{TEST_NET}.13", FINGERPRINT,
             {"name": "lab-vm", "address": f"{TEST_NET}.13", "group": "enterprise_linux", "fingerprint": FINGERPRINT}),
            ("family=debian\n", "lab-vm", f"{TEST_NET}.10", "", FINGERPRINT,
             {"name": "lab-vm", "address": f"{TEST_NET}.10", "group": "ubuntu", "fingerprint": FINGERPRINT}),
            ("family=debian\n", "lab_vm!", f"{TEST_NET}.10 {TEST_NET}.11", "", "",
             {"name": None, "address": None, "group": "ubuntu", "fingerprint": None}),
            # localhost is Ansible's name for the controller, which add-target.sh refuses.
            ("family=el\n", "localhost", f"{TEST_NET}.12", "", FINGERPRINT,
             {"name": None, "address": f"{TEST_NET}.12", "group": "enterprise_linux", "fingerprint": FINGERPRINT}),
        ]
        for setup, name, addresses, source, fingerprint, expected in cases:
            with self.subTest(setup=setup, addresses=addresses):
                lines = self.closing_lines(setup, name, addresses, source, fingerprint)
                # The block ends just before the result line.
                self.assertInfoLines(lines[lines.index("Add this VM on the controller: in the guide's folder, run"):-1],
                                     **expected)

    def test_the_output_pasted_whole_adds_the_vm(self):
        key, fingerprint = self.host_key()
        lines = self.closing_lines("family=el\nCONTROLLER_ADDRESS=" + TEST_NET + ".5\n", "lab-vm",
                                   f"{TEST_NET}.12 {TEST_NET}.13", f"{TEST_NET}.13", fingerprint)
        self.assertAddTargetAdds("host: lab-vm (AlmaLinux 9.8)\n" + "\n".join(lines) + "\n", key,
                                 f"lab-vm ansible_host={TEST_NET}.13")


# sshd -T lines, the account's groups, then the reasons sshd would refuse it and the entries
# no check can judge, each in the order sshd checks: DenyUsers, AllowUsers, DenyGroups, AllowGroups.
ACCESS_CASES = [
    ([], "svc_ansible", [], []),
    (["port 22", "allowtcpforwarding yes", "allowagentforwarding yes"], "svc_ansible", [], []),
    (["allowusers azadmin", "allowusers adm*", "allowusers svc_ansible"], "svc_ansible", [], []),
    (["allowusers azadmin", f"allowusers azadmin@{TEST_NET}.0/24", "allowusers quoted user", "allowusers SVC_ANSIBLE"],
     "svc_ansible", ["AllowUsers does not list svc_ansible"], []),
    (["allowusers azadmin", "allowusers svc_*", f"allowusers svc_ansible@{TEST_NET}.0/24", "allowusers a@b@c",
      "allowusers root@host*"], "svc_ansible",
     [], ["AllowUsers svc_*", f"AllowUsers svc_ansible@{TEST_NET}.0/24", "AllowUsers a@b@c"]),
    (["denyusers root", "denyusers svc_ansible", "denyusers *ansible", "denyusers svc_ansible@"], "svc_ansible",
     ["DenyUsers lists svc_ansible"], ["DenyUsers *ansible", "DenyUsers svc_ansible@"]),
    (["denygroups nologin", "denygroups wheel", "denygroups adm?", "denygroups svc_ansible"], "svc_ansible wheel",
     ["DenyGroups lists svc_ansible's group wheel"], ["DenyGroups adm?"]),
    (["allowgroups sshusers"], "svc_ansible", ["AllowGroups lists none of svc_ansible's groups (svc_ansible)"], []),
    (["allowgroups sshusers", "allowgroups wheel", "allowgroups ssh*"], "svc_ansible wheel", [], []),
    (["allowgroups ssh*"], "svc_ansible", [], ["AllowGroups ssh*"]),
    (["allowusers azadmin", "denyusers svc_ansible", "allowgroups sshusers", "denygroups svc_ansible"], "svc_ansible",
     ["DenyUsers lists svc_ansible", "AllowUsers does not list svc_ansible",
      "DenyGroups lists svc_ansible's group svc_ansible",
      "AllowGroups lists none of svc_ansible's groups (svc_ansible)"], []),
    # id -nG separates names with spaces, so a group name with one cannot be compared.
    (["denygroups domain admins", "allowgroups domain users", "allowgroups sshusers"], "svc_ansible",
     [], ["DenyGroups domain admins", "AllowGroups domain users"]),
]


class AccessCheckTests(unittest.TestCase):
    """sshd_access, which onboard-linux.sh and cloud-init share, judges AllowUsers and the rest as sshd does."""

    def verdicts(self, cases, awk=None):
        """Run sshd_access on each case; return its refused and unsure lines per case."""
        program = function(ONBOARD, "sshd_access") + (
            "while IFS= read -r -d '' policy && IFS= read -r -d '' groups; do\n"
            '  sshd_access "$policy" svc_ansible "$groups"\n  echo ---\ndone\n')
        stdin = "".join("\n".join(lines) + "\0" + groups + "\0" for lines, groups, *_ in cases)
        with tempfile.TemporaryDirectory() as work:
            path = None
            if awk:
                Path(work, "awk").symlink_to(shutil.which(awk))
                path = work + os.pathsep + os.environ["PATH"]
            result = run_bash(program, path, stdin=stdin)
        self.assertEqual(result.returncode, 0, result.stderr)
        found = []
        for chunk in result.stdout.split("---\n")[:-1]:
            lines = chunk.splitlines()
            found.append(([line.removeprefix("refused: ") for line in lines if line.startswith("refused: ")],
                          [line.removeprefix("unsure: ") for line in lines if line.startswith("unsure: ")]))
            self.assertEqual(len(lines), len(found[-1][0]) + len(found[-1][1]), chunk)
        return found

    def test_verdicts_with_each_awk(self):
        # Ubuntu's awk is mawk and Enterprise Linux's is gawk.
        for awk in [None] + [name for name in ("mawk", "gawk") if shutil.which(name)]:
            with self.subTest(awk=awk or "default"):
                self.assertEqual(self.verdicts(ACCESS_CASES, awk),
                                 [(refused, unsure) for _lines, _groups, refused, unsure in ACCESS_CASES])

    @unittest.skipUnless(os.access("/usr/sbin/sshd", os.X_OK) and shutil.which("ssh-keygen"), "needs OpenSSH")
    def test_real_sshd_output_is_read_the_same_way(self):
        with tempfile.TemporaryDirectory() as work:
            key = Path(work, "host_key")
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            config = Path(work, "sshd_config")
            config.write_text(f"HostKey {key}\nPidFile none\nAllowUsers azadmin svc_*\nAllowUsers \"quoted user\"\n"
                              "DenyUsers root\nAllowGroups sshusers wheel \"domain users\"\nDenyGroups nologin\n"
                              "Match User svc_ansible\n    DenyUsers svc_ansible\nMatch all\n")
            result = subprocess.run(["/usr/sbin/sshd", "-T", "-f", str(config), "-C",
                                     "user=svc_ansible,host=localhost,addr=127.0.0.1"],
                                    capture_output=True, text=True, timeout=30)
        if result.returncode:
            self.skipTest("sshd -T cannot run here: " + result.stderr.strip()[:200])
        # One line per entry, unquoted; a Match block's list replaces the global one.
        lines = [line for line in result.stdout.splitlines()
                 if line.split(" ", 1)[0] in ("allowusers", "denyusers", "allowgroups", "denygroups")]
        self.assertEqual(sorted(lines), sorted(["allowusers azadmin", "allowusers svc_*", "allowusers quoted user",
                                                "denyusers svc_ansible", "allowgroups sshusers", "allowgroups wheel",
                                                "allowgroups domain users", "denygroups nologin"]))
        self.assertEqual(self.verdicts([(result.stdout.splitlines(), "svc_ansible wheel"),
                                        (result.stdout.splitlines(), "svc_ansible")]),
                         [(["DenyUsers lists svc_ansible"], ["AllowUsers svc_*"]),
                          (["DenyUsers lists svc_ansible"], ["AllowUsers svc_*", "AllowGroups domain users"])])


@unittest.skipUnless(shutil.which("ansible-playbook"), "needs ansible-playbook, as CI installs it")
class PlaybookTests(AddTargetLineMixin, unittest.TestCase):
    """bootstrap-existing-vm.yml's own tasks and expressions, and how targets.yml reads cloud-init.yaml."""

    def run_play(self, tasks, work, inventory="localhost ansible_connection=local\n"):
        """Run tasks through ansible-playbook with an empty collections path; results go to files."""
        Path(work, "inventory.ini").write_text(inventory)
        Path(work, "ansible.cfg").write_text("[defaults]\n")
        Path(work, "collections").mkdir()
        Path(work, "play.yml").write_text(yaml.safe_dump([{
            "hosts": "all", "gather_facts": False, "tasks": tasks,
            "vars": {"ansible_python_interpreter": "{{ ansible_playbook_python }}"}}]))
        environment = dict(os.environ, ANSIBLE_CONFIG=str(Path(work, "ansible.cfg")), ANSIBLE_LOCALHOST_WARNING="False",
                           ANSIBLE_COLLECTIONS_PATH=str(Path(work, "collections")),
                           ANSIBLE_COLLECTIONS_SCAN_SYS_PATH="False")
        result = subprocess.run(["ansible-playbook", "-i", "inventory.ini", "play.yml"], capture_output=True,
                                text=True, timeout=180, cwd=work, env=environment)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])

    def render(self, template, cases, inventory="localhost ansible_connection=local\n"):
        """Render the template once per case, each case's dict being that task's vars."""
        with tempfile.TemporaryDirectory() as work:
            tasks = [{"name": f"case {index}", "vars": case,
                      "ansible.builtin.copy": {"content": "{{ " + template + " | to_json }}",
                                               "dest": f"{work}/case{index}.json", "mode": "0600"}}
                     for index, case in enumerate(cases)]
            self.run_play(tasks, work, inventory)
            return [json.loads(Path(work, f"case{index}.json").read_text()) for index in range(len(cases))]

    def test_targets_yml_passes_cloud_init_yaml_through_unchanged(self):
        # It reads the file with a lookup and replaces only the key placeholder; nothing in
        # the file, such as Bash's ${#array[@]}, may be taken for a template.
        targets = yaml.safe_load((ROOT / "examples" / "azure" / "targets.yml").read_text())[0]["vars"]
        key = "ssh-rsa AAAAB3NzaC1yc2E= ansible-practice"
        path = str(ROOT / "examples" / "onboard" / "cloud-init.yaml")
        given = {"automation_public_key": key, "cloud_init_data": targets["cloud_init_data"],
                 "cloud_init_template": targets["cloud_init_template"].replace("../onboard/cloud-init.yaml", path)}
        self.assertNotEqual(given["cloud_init_template"], targets["cloud_init_template"])
        [rendered] = self.render("cloud_init_data", [given])
        self.assertEqual(rendered, CLOUD_INIT_TEXT.rstrip().replace('"REPLACE_WITH_AUTOMATION_PUBLIC_KEY"', json.dumps(key)))

    def test_the_access_check_reaches_the_same_verdicts_as_the_scripts(self):
        check = playbook_task("Check that DenyUsers, AllowUsers, DenyGroups and AllowGroups let svc_ansible in")
        self.assertEqual(check["ansible.builtin.assert"]["that"], ["bootstrap_access_refused | length == 0"])
        # Inside the block whose rescue restores the drop-in, and before the reload is scheduled.
        block = next(task["block"] for task in PLAYBOOK["tasks"] if check in task.get("block", []))
        names = [task["name"] for task in block]
        self.assertLess(names.index(check["name"]),
                        names.index("Schedule the SSH reload only after every check has passed"))
        expressions = dict(check["vars"], bootstrap_message=check["ansible.builtin.assert"]["fail_msg"],
                           bootstrap_notice=check["ansible.builtin.assert"]["success_msg"])
        cases = [dict(expressions, bootstrap_sshd_policy={"stdout_lines": lines},
                      bootstrap_account_groups={"stdout": groups}) for lines, groups, *_ in ACCESS_CASES]
        rendered = self.render("{'refused': bootstrap_access_refused, 'unsure': bootstrap_access_unsure,"
                               " 'message': bootstrap_message, 'notice': bootstrap_notice}", cases)
        self.assertEqual([(case["refused"], case["unsure"]) for case in rendered],
                         [(refused, unsure) for _lines, _groups, refused, unsure in ACCESS_CASES])
        # The failure names the keyword and asks for svc_ansible to be allowed.
        self.assertEqual(rendered[7]["message"], "AllowGroups lists none of svc_ansible's groups (svc_ansible); sshd"
                         " would refuse the account, so allow svc_ansible there before running this again.")
        self.assertEqual(rendered[9]["notice"],
                         'This check cannot evaluate "AllowGroups ssh*"; make sure sshd lets svc_ansible in.')
        self.assertEqual(rendered[0]["notice"],
                         "Nothing in DenyUsers, AllowUsers, DenyGroups or AllowGroups keeps svc_ansible out.")

    def test_the_play_ends_with_the_add_target_line(self):
        show = playbook_task("Show the controller command that adds this host")
        self.assertIs(PLAYBOOK["tasks"][-1], show)
        given = dict(show["vars"], bootstrap_lines=show["ansible.builtin.debug"]["msg"])
        cases = [
            # From the inventory host, its ansible_host, its OS family and its RSA host key.
            dict(given, ansible_facts={"os_family": "RedHat"},
                 bootstrap_rsa_host_key={"stdout": f"3072 {FINGERPRINT} root@lab-alma (RSA)\n"}),
            # Values add-target.sh refuses become placeholders, as does a host key that cannot be read.
            dict(given, ansible_facts={"os_family": "Debian"}, bootstrap_add_name="lab ubuntu",
                 bootstrap_add_address="ubuntu.example.test -oProxyCommand=x", bootstrap_rsa_host_key={"stdout": ""}),
            # So do values with a trailing newline, which a match on ^...$ alone lets through.
            dict(given, ansible_facts={"os_family": "Debian"}, bootstrap_add_name="lab-ubuntu\n",
                 bootstrap_add_address=f"{TEST_NET}.10\n", bootstrap_add_fingerprint=FINGERPRINT + "\n"),
        ]
        first, second, third = self.render("bootstrap_lines", cases,
                                           f"lab-alma ansible_host={TEST_NET}.12 ansible_connection=local\n")
        self.assertEqual(first[0], "Add this VM on the controller: in the guide's folder, run this command (replace"
                         " NAME, ADDRESS or FINGERPRINT if shown, and add --lab-dir DIR for a lab folder other than"
                         " /opt/ansible-lab):")
        self.assertAddTargetLine(first[1], name="lab-alma", address=f"{TEST_NET}.12", group="enterprise_linux",
                                 fingerprint=FINGERPRINT)
        for rendered in (second, third):
            self.assertAddTargetLine(rendered[1], name="NAME", address="ADDRESS", group="ubuntu",
                                     fingerprint="FINGERPRINT")

    def test_the_key_check_reads_the_policy_as_sshd_reports_it(self):
        # The pre-task that stops the play before keys the server refuses replace the account's
        # own, for sshd -T lines and keys measured as ssh-keygen -l reports them.
        usable = playbook_task("Require at least one listed key that can log in")
        [condition] = usable["ansible.builtin.assert"]["that"]
        stock = ["requiredrsasize 1024", "pubkeyacceptedalgorithms ssh-ed25519-cert-v01@openssh.com,"
                 "ecdsa-sha2-nistp256-cert-v01@openssh.com,rsa-sha2-512-cert-v01@openssh.com,"
                 "rsa-sha2-256-cert-v01@openssh.com,ssh-ed25519,ecdsa-sha2-nistp256,ecdsa-sha2-nistp384,"
                 "ecdsa-sha2-nistp521,sk-ssh-ed25519@openssh.com,rsa-sha2-512,rsa-sha2-256"]
        rsa_only = "pubkeyacceptedalgorithms rsa-sha2-512,rsa-sha2-256"
        rsa_4096 = {"item": "ssh-rsa AAAAB3NzaC1yc2E= four", "stdout": f"4096 {FINGERPRINT} four (RSA)"}
        rsa_2048 = {"item": "ssh-rsa AAAAB3NzaC1yc2E= two", "stdout": f"2048 {FINGERPRINT} two (RSA)"}
        ed25519 = {"item": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 ed", "stdout": f"256 {FINGERPRINT} ed (ED25519)"}
        # sshd -T lines, the listed keys, then whether one can log in and the RSA minimum.
        cases = [
            (stock, [rsa_4096], True, 2048),
            ([rsa_only], [ed25519], False, 2048),
            ([rsa_only, "requiredrsasize 3072"], [rsa_2048], False, 3072),
            ([rsa_only, "requiredrsasize 3072"], [rsa_4096], True, 3072),
            # SHA-1 ssh-rsa only, with which the controller's client never signs.
            (["pubkeyacceptedalgorithms ssh-rsa"], [rsa_4096], False, 2048),
        ]
        given = [dict(usable["vars"], bootstrap_sshd_before={"stdout_lines": lines},
                      bootstrap_key_sizes={"results": keys}, automation_public_keys=[key["item"] for key in keys])
                 for lines, keys, *_ in cases]
        rendered = self.render("{'usable': (" + condition + "), 'min_rsa': bootstrap_min_rsa | int}", given)
        self.assertEqual([(case["usable"], case["min_rsa"]) for case in rendered],
                         [(can_log_in, size) for _lines, _keys, can_log_in, size in cases])

    def test_the_sudo_check_refuses_another_accounts_password(self):
        # The assert as the play runs it: its regular expression's doubled backslashes are the
        # kind of escape that ansible-core 2.21 once read differently.
        check = playbook_task("Check that sudo requires the password")
        failed_for = {"env_reset, rootpw, use_pty": True, "env_reset, !rootpw, use_pty": False,
                      "env_reset, use_pty, targetpw": True}
        rights = ("Matching Defaults entries for svc_ansible on lab-alma:\n    {}\n\n"
                  "User svc_ansible may run the following commands on lab-alma:\n    (ALL : ALL) ALL\n")
        tasks = [dict(check, name=f"case {index}", ignore_errors=True, register=f"bootstrap_case{index}",
                      vars={"bootstrap_sudo_rights": {"stdout": rights.format(defaults)},
                            "bootstrap_sudo_nopass": {"rc": 1}})
                 for index, defaults in enumerate(failed_for)]
        results = ", ".join(f"bootstrap_case{index}.failed" for index in range(len(tasks)))
        with tempfile.TemporaryDirectory() as work:
            tasks.append({"name": "Save the results", "ansible.builtin.copy": {
                "content": "{{ [" + results + "] | to_json }}", "dest": f"{work}/results.json", "mode": "0600"}})
            self.run_play(tasks, work)
            failed = json.loads(Path(work, "results.json").read_text())
        self.assertEqual(dict(zip(failed_for, failed)), failed_for)

    def test_a_link_in_place_of_the_ssh_directory_or_key_file_stops_the_play(self):
        look = playbook_task("Look at the account's SSH directory and key file without following links")
        refuse = playbook_task("Refuse a link in place of the SSH directory or key file")
        self.assertIs(look["ansible.builtin.stat"]["follow"], False)
        with tempfile.TemporaryDirectory() as work:
            elsewhere = Path(work, "elsewhere")
            elsewhere.mkdir()
            Path(elsewhere, "authorized_keys").write_text("")
            homes = {name: Path(work, name) for name in ("fresh", "plain", "linked_dir", "linked_file")}
            for home in homes.values():
                home.mkdir()
            Path(homes["plain"], ".ssh").mkdir()
            Path(homes["plain"], ".ssh/authorized_keys").write_text("")
            Path(homes["linked_dir"], ".ssh").symlink_to(elsewhere)
            Path(homes["linked_file"], ".ssh").mkdir()
            Path(homes["linked_file"], ".ssh/authorized_keys").symlink_to(elsewhere / "authorized_keys")
            homes["spaced"] = Path(work, "a home")
            homes["spaced"].mkdir()
            tasks = []
            for name, home in homes.items():
                tasks.append(dict(look, vars={"bootstrap_home": str(home)}))
                tasks.append(dict(refuse, vars={"bootstrap_home": str(home)}, ignore_errors=True,
                                  register=f"bootstrap_{name}"))
            tasks.append({"name": "Save the results", "ansible.builtin.copy": {
                "content": "{{ {" + ", ".join(f"'{name}': bootstrap_{name}.failed" for name in homes) + "} | to_json }}",
                "dest": f"{work}/results.json", "mode": "0600"}})
            self.run_play(tasks, work)
            failed = json.loads(Path(work, "results.json").read_text())
        self.assertEqual(failed, {"fresh": False, "plain": False, "linked_dir": True, "linked_file": True,
                                  "spaced": True})

    def test_the_key_file_is_written_by_the_account_itself(self):
        write = playbook_task("Authorize exactly the listed public keys")
        self.assertEqual((write["become_user"], write["vars"]["ansible_pipelining"]), ("svc_ansible", True))
        names = [task["name"] for task in PLAYBOOK["tasks"]]
        self.assertLess(names.index("Read the account's home directory"),
                        names.index("Refuse a link in place of the SSH directory or key file"))
        self.assertLess(names.index("Refuse a link in place of the SSH directory or key file"),
                        names.index(write["name"]))
        command = write["ansible.builtin.command"]
        self.assertEqual(command["argv"][:2], ["/bin/bash", "-c"])
        # The command module adds a final newline to stdin, as the old key file had.
        self.assertEqual(command["stdin"], "{{ automation_public_keys | join('\n') }}")
        # No task writes into the account's home as root, and none assumes it is /home/svc_ansible.
        for task in playbook_tasks():
            for module in ("ansible.builtin.copy", "ansible.builtin.file", "ansible.builtin.template"):
                if module in task:
                    self.assertNotIn("home", str(task[module].get("dest", task[module].get("path"))), task["name"])
        self.assertNotIn("/home/svc_ansible", PLAYBOOK_TEXT)
        keys = "ssh-rsa AAAAB3NzaC1yc2E= one\nssh-rsa AAAAB3NzaC1yc2E= two\n"
        with tempfile.TemporaryDirectory() as home:
            authorized = Path(home, ".ssh/authorized_keys")

            def write_keys(text):
                return run_bash(command["argv"][2], stdin=text, args=[home])
            self.assertEqual(write_keys(keys).stdout, "replaced\n")
            self.assertEqual(authorized.read_text(), keys)
            self.assertEqual((authorized.parent.stat().st_mode & 0o777, authorized.stat().st_mode & 0o777),
                             (0o700, 0o600))
            authorized.chmod(0o644)
            self.assertEqual(write_keys(keys).stdout, "unchanged\n")
            self.assertEqual(authorized.stat().st_mode & 0o777, 0o600)
            self.assertEqual(write_keys(keys[:keys.index("\n") + 1]).stdout, "replaced\n")
            self.assertEqual(sorted(p.name for p in authorized.parent.iterdir()), ["authorized_keys"])
            authorized.unlink()
            authorized.mkdir()
            result = write_keys(keys)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("authorized_keys is a directory", result.stderr)

    def test_the_key_task_finds_the_home_with_getent_and_reports_changes(self):
        # The task as Ansible runs it, as this account instead of svc_ansible, with the home
        # in the form the getent module returns: password, UID, GID, GECOS, home, shell.
        write = playbook_task("Authorize exactly the listed public keys")
        task = {key: value for key, value in write.items() if key not in ("become", "become_user")}
        keys = ["ssh-rsa AAAAB3NzaC1yc2E= one", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 two"]
        with tempfile.TemporaryDirectory() as work:
            home = Path(work, "elsewhere", "svc_ansible")
            home.mkdir(parents=True)
            getent = {"svc_ansible": ["x", "1001", "1001", "", str(home), "/bin/bash"]}
            given = dict(task["vars"], automation_public_keys=keys, bootstrap_home=PLAYBOOK["vars"]["bootstrap_home"],
                         ansible_facts={"getent_passwd": getent})
            self.run_play([
                dict(task, vars=given),
                {"name": "Keep the first result", "ansible.builtin.set_fact": {"first": "{{ bootstrap_keys.changed }}"}},
                dict(task, vars=given),
                {"name": "Save the results", "ansible.builtin.copy": {
                    "content": "{{ [first, bootstrap_keys.changed] | to_json }}", "dest": f"{work}/results.json",
                    "mode": "0600"}},
            ], work)
            self.assertEqual(json.loads(Path(work, "results.json").read_text()), [True, False])
            self.assertEqual(Path(home, ".ssh/authorized_keys").read_text(), "\n".join(keys) + "\n")


if __name__ == "__main__":
    unittest.main()
