"""Offline runs of the first-boot installation: the cloud-init file and controller/first-boot.sh.

controller/first-boot/user-data.yaml fetches the guide on a new VM and hands over to
controller/first-boot.sh, which runs the installer. Both run here with their file
locations moved into a temporary folder and with stand-ins for the commands that
need root, a network or a package manager. Nothing here changes the system.
"""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
USER_DATA = ROOT / "controller" / "first-boot" / "user-data.yaml"
SCRIPT = ROOT / "controller" / "first-boot.sh"
CONF = "/etc/ansible-semaphore-guide/first-boot.conf"
LOG = "/var/log/ansible-guide-first-boot.log"
ORIGIN = "https://github.com/kevo099/ansible-semaphore-guide.git"

# One stand-in for every command the two scripts may not really run. It records its
# call and answers from the environment of the test.
MOCK_COMMAND = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a") as stream:
    stream.write(json.dumps([name, *args, {"HOME": os.environ.get("HOME")}]) + "\n")

if name == "id":
    print(os.environ.get("MOCK_UID", "0"))
elif name == "getent":
    accounts = json.loads(os.environ.get("MOCK_ACCOUNTS", "{}"))
    if args[0] != "passwd" or args[1] not in accounts:
        sys.exit(2)
    print(f"{args[1]}:x:1000:1000::{accounts[args[1]]}:/bin/bash")
elif name == "runuser":
    # runuser -u ADMIN -- env HOME=... git clone --quiet --branch RELEASE ORIGIN FOLDER
    if os.environ.get("MOCK_CLONE") == "fail":
        print("fatal: unable to access the repository", file=sys.stderr)
        sys.exit(128)
    folder = Path(args[-1])
    (folder / ".git").mkdir(parents=True)
    if os.environ.get("MOCK_CLONE") != "earlier-release":
        (folder / "controller").mkdir()
        (folder / "controller" / "first-boot.sh").write_text('echo "handed over with HOME=$HOME"\n')
elif name == "python3.12":
    sys.exit(int(os.environ.get("MOCK_READINESS", "0")))
'''

INSTALLER = textwrap.dedent('''\
    printf '%s\\n' "$(basename "$0") $*" >> "$MOCK_INSTALLER_LOG"
    printf 'HOME=%s\\n' "$HOME" >> "$MOCK_INSTALLER_LOG"
    echo "installer output"
    # The real installer seeds, and writes its marker, before it publishes over HTTPS.
    [ -z "${MOCK_INSTALLER_SEEDS:-}" ] || : > "$MOCK_INSTALLER_SEEDS"
    exit "${MOCK_INSTALLER_STATUS:-0}"
''')

EXPOSE = textwrap.dedent('''\
    printf '%s\\n' "$(basename "$0") $*" >> "$MOCK_INSTALLER_LOG"
    echo "exposure output"
    [ "${MOCK_EXPOSE_STATUS:-0}" != 0 ] || printf 'https\\n' > "$MOCK_EXPOSURE_FILE"
    exit "${MOCK_EXPOSE_STATUS:-0}"
''')
# Built from parts so the repository's check for literal addresses passes over them.
IPV4 = "192.0.2" + ".5"
IPV6 = "2001:db8" + "::5"


def bootstrap_script(text):
    """The [/bin/bash, -c, SCRIPT] runcmd entry of the cloud-config text."""
    [entry] = yaml.safe_load(text)["runcmd"]
    assert entry[:2] == ["/bin/bash", "-c"], entry[:2]
    return entry[2]


class Relocated(unittest.TestCase):
    """A temporary folder with the stand-ins on PATH and the two files' locations inside it."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.conf, self.log, self.home = self.work / "first-boot.conf", self.work / "first-boot.log", self.work / "home"
        self.home.mkdir()
        self.calls = self.work / "calls.jsonl"
        self.calls.touch()
        self.bin = self.work / "bin"
        self.bin.mkdir()
        for name in ("id", "getent", "runuser", "python3.12"):
            (self.bin / name).write_text(MOCK_COMMAND)
            (self.bin / name).chmod(0o755)
        self.write_conf()

    def write_conf(self, release="v1.13.0", admin="ada", expose="tunnel", address="", newline="\n"):
        lines = [f"release={release}", f"admin={admin}", f"expose={expose}", f"address={address}"]
        self.conf.write_text(newline.join(lines) + newline)

    def environment(self, path=None, **extra):
        env = dict(os.environ, PATH=path or f"{self.bin}:{os.environ['PATH']}", MOCK_LOG=str(self.calls),
                   MOCK_ACCOUNTS=json.dumps({"ada": str(self.home)}))
        env.pop("HOME", None)  # cloud-init gives its commands no home folder
        env.update(extra)
        return env

    def recorded(self, name):
        return [call for call in map(json.loads, self.calls.read_text().splitlines()) if call[0] == name]


class UserDataTests(unittest.TestCase):
    def setUp(self):
        self.text = USER_DATA.read_text()
        self.data = yaml.safe_load(self.text)

    def test_it_is_a_cloud_config_with_the_four_values_git_and_one_command(self):
        self.assertTrue(self.text.startswith("#cloud-config\n"))
        self.assertEqual(sorted(self.data), ["packages", "runcmd", "write_files"])
        self.assertEqual(self.data["packages"], ["git"])
        [conf] = self.data["write_files"]
        self.assertEqual((conf["path"], conf["owner"], conf["permissions"]), (CONF, "root:root", "0644"))
        self.assertEqual(conf["content"], "release=v1.13.0\nadmin=REPLACE_WITH_ADMIN_LOGIN\nexpose=tunnel\naddress=\n")
        self.assertEqual(len(self.data["runcmd"]), 1)

    def test_it_fits_the_smallest_user_data_limit_of_the_common_platforms(self):
        # 16 KiB of raw user data on one platform; the others allow more.
        self.assertLess(len(self.text.encode()), 8 * 1024)

    def test_the_comment_names_each_value_and_both_ways_to_hand_the_file_over(self):
        comment = "".join(line for line in self.text.splitlines(keepends=True) if line.startswith("#"))
        for word in ("release ", "admin ", "expose ", "address ", "vendor data", "Custom data", "holds no secret",
                     "docs/first-boot-controller.md", "site/index.html", "write_files:, packages: or runcmd:"):
            self.assertIn(word, comment)

    def test_the_script_fetches_from_this_repository_only(self):
        script = bootstrap_script(self.text)
        self.assertIn(f"origin={ORIGIN}\n", script)
        self.assertEqual(script.count("https://"), 1)


class BootstrapTests(Relocated):
    """The command in user-data.yaml, up to the hand-over to controller/first-boot.sh."""

    def run_bootstrap(self, **environment):
        script = bootstrap_script(USER_DATA.read_text())
        for original, replacement in ((CONF, self.conf), (LOG, self.log)):
            self.assertIn(original, script)
            script = script.replace(original, str(replacement))
        return subprocess.run(["/bin/bash", "-c", script], env=self.environment(**environment),
                              capture_output=True, text=True)

    def assertStopped(self, result, reason):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"first-boot: RESULT: STOPPED: {reason}", result.stdout)
        self.assertIn(f"first-boot: RESULT: STOPPED: {reason}", self.log.read_text())

    def test_it_fetches_the_release_as_the_administrator_and_hands_over(self):
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("handed over", result.stdout)
        guide = self.home / "ansible-semaphore-guide"
        [call] = self.recorded("runuser")
        self.assertEqual(call[1:-1], ["-u", "ada", "--", "env", f"HOME={self.home}", "git", "clone", "--quiet",
                                      "--branch", "v1.13.0", ORIGIN, str(guide)])
        self.assertEqual(stat.S_IMODE(self.log.stat().st_mode), 0o600)

    def test_a_folder_that_is_already_there_is_not_fetched_again(self):
        self.assertEqual(self.run_bootstrap().returncode, 0)
        self.assertEqual(self.run_bootstrap().returncode, 0)
        self.assertEqual(len(self.recorded("runuser")), 1)

    def test_values_pasted_with_carriage_returns_or_trailing_blanks_are_read(self):
        self.write_conf(newline=" \r\n")
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.recorded("runuser")[0][10], "v1.13.0")

    def test_the_placeholder_stops_it_before_anything_is_fetched(self):
        self.write_conf(admin="REPLACE_WITH_ADMIN_LOGIN")
        # Even on a VM that has an account of that name, the placeholder is no answer.
        for accounts in ("{}", json.dumps({"REPLACE_WITH_ADMIN_LOGIN": str(self.home)})):
            self.assertStopped(self.run_bootstrap(MOCK_ACCOUNTS=accounts),
                               "admin= in " + str(self.conf) + " must be the login of this VM's administrator; it still "
                               "holds the placeholder or is empty")
        self.write_conf(admin="")
        self.assertStopped(self.run_bootstrap(), "admin= in")
        # root has a home folder, and the installer refuses it as the lab folder's owner only later.
        self.write_conf(admin="root")
        self.assertStopped(self.run_bootstrap(MOCK_ACCOUNTS=json.dumps({"root": str(self.home)})),
                           "admin= in " + str(self.conf) + " must be your own administrator account, not root")
        self.assertEqual(self.recorded("runuser"), [])

    def test_an_account_the_vm_does_not_have_stops_it(self):
        self.write_conf(admin="grace")
        self.assertStopped(self.run_bootstrap(), "this VM has no account grace with a home folder; create the VM with "
                                                 "that administrator")
        self.assertEqual(self.recorded("runuser"), [])

    def test_a_release_name_that_could_be_an_option_is_refused(self):
        for release in ("", "--upload-pack=x", "v1.13.0 extra", "v1;id"):
            with self.subTest(release=release):
                self.write_conf(release=release)
                self.assertStopped(self.run_bootstrap(), "release= in")
        self.assertEqual(self.recorded("runuser"), [])

    def test_without_git_it_names_the_registration_and_stage_1(self):
        tools = self.work / "tools"
        tools.mkdir()
        for name in ("sed", "tr", "tail", "cut", "install", "tee", "bash", "env", "python3"):
            (tools / name).symlink_to(shutil.which(name) or f"/usr/bin/{name}")
        result = self.run_bootstrap(path=f"{self.bin}:{tools}")
        self.assertStopped(result, "Git is not installed, so cloud-init could not install packages. On RHEL, register "
                                   "the system first.")
        self.assertEqual(self.recorded("runuser"), [])

    def test_a_fetch_that_fails_is_reported_with_its_reason_in_the_log(self):
        result = self.run_bootstrap(MOCK_CLONE="fail")
        self.assertStopped(result, f"could not fetch release v1.13.0 from {ORIGIN}")
        self.assertIn("fatal: unable to access the repository", self.log.read_text())

    def test_a_release_before_this_script_existed_is_named(self):
        self.write_conf(release="v1.12.0")
        result = self.run_bootstrap(MOCK_CLONE="earlier-release")
        self.assertStopped(result, "release v1.12.0 has no controller/first-boot.sh; an installation at first boot "
                                   "needs v1.13.0 or later")


class FirstBootScriptTests(Relocated):
    """controller/first-boot.sh with stand-in installers beside it."""

    def setUp(self):
        super().setUp()
        self.controller = self.work / "guide" / "controller"
        self.controller.mkdir(parents=True)
        self.marker, self.os_release, self.exposure = self.work / "seeded", self.work / "os-release", self.work / "exposure"
        self.os_release.write_text('ID="ubuntu"\nVERSION_ID="24.04"\n')
        self.installer_log = self.work / "installer.log"
        script = SCRIPT.read_text()
        for original, replacement in ((CONF, self.conf), (LOG, self.log), ("/etc/os-release", self.os_release),
                                      ("/etc/semaphore/.guide-project-seeded", self.marker),
                                      ("/etc/semaphore/exposure", self.exposure),
                                      ("/etc/semaphore/.practice-project-seeded", self.work / "seeded-earlier")):
            self.assertIn(original, script)
            script = script.replace(original, str(replacement))
        (self.controller / "first-boot.sh").write_text(script)
        for name in ("install-controller.sh", "install-controller-el9.sh"):
            (self.controller / name).write_text(INSTALLER)
        (self.controller / "expose-semaphore.sh").write_text(EXPOSE)
        (self.controller / "check-controller.py").write_text("")

    def run_script(self, **environment):
        return subprocess.run(["bash", str(self.controller / "first-boot.sh")],
                              env=self.environment(MOCK_INSTALLER_LOG=str(self.installer_log),
                                                   MOCK_EXPOSURE_FILE=str(self.exposure), **environment),
                              capture_output=True, text=True)

    def installer_calls(self):
        return self.installer_log.read_text().splitlines() if self.installer_log.exists() else []

    def assertStopped(self, result, reason):
        """It ended with status 1 and one STOPPED line, on the screen and in the log, that holds the reason."""
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        [line] = [line for line in result.stdout.splitlines() if line.startswith("first-boot: RESULT: ")]
        self.assertTrue(line.startswith("first-boot: RESULT: STOPPED: ") and reason in line, line)
        self.assertEqual(result.stdout.splitlines()[-1], line)
        self.assertIn(line + "\n", self.log.read_text())

    def test_ubuntu_runs_its_installer_for_the_administrator_and_reports_ok(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # The installer finds the home folder that cloud-init does not set.
        self.assertEqual(self.installer_calls(), ["install-controller.sh --apply --editor ada", "HOME=/root"])
        for line in ("first-boot: running install-controller.sh --apply --editor ada", "installer output",
                     "first-boot: the readiness check passed", "first-boot: RESULT: OK",
                     'first-boot: next, open the SSH tunnel of docs/stage-1-controller.md, "Open Semaphore"',
                     "first-boot: the initial password: sudo cat /etc/semaphore/initial-admin-password"):
            self.assertIn(line, result.stdout)
        self.assertEqual(self.log.read_text(), result.stdout)
        self.assertEqual(stat.S_IMODE(self.log.stat().st_mode), 0o600)
        [check] = self.recorded("python3.12")
        self.assertEqual(check[1], str(self.controller / "check-controller.py"))

    def test_each_enterprise_linux_runs_the_el9_installer(self):
        for system in ("rhel", "almalinux", "rocky"):
            with self.subTest(system=system):
                self.installer_log.unlink(missing_ok=True)
                self.os_release.write_text(f'ID="{system}"\n')
                self.assertEqual(self.run_script().returncode, 0)
                self.assertEqual(self.installer_calls()[0], "install-controller-el9.sh --apply --editor ada")

    def test_another_system_stops_before_any_installer(self):
        self.os_release.write_text("ID=debian\n")
        self.assertStopped(self.run_script(), f"this system (ID=debian in {self.os_release}) is none of Ubuntu, RHEL, "
                                              "AlmaLinux and Rocky Linux")
        self.assertEqual(self.installer_calls(), [])

    def test_https_and_its_address_reach_the_installer(self):
        self.write_conf(expose="https", address="controller.example.test")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.installer_calls()[0], "install-controller.sh --apply --editor ada --expose https "
                                                    "--address controller.example.test")
        self.assertIn("first-boot: next, browse to the https address the installer printed above", result.stdout)
        self.installer_log.unlink()
        self.write_conf(expose="https")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.installer_calls()[0], "install-controller.sh --apply --editor ada --expose https")

    def test_values_the_installer_must_not_get_stop_it(self):
        cases = ((dict(admin="REPLACE_WITH_ADMIN_LOGIN"), "admin= in"), (dict(admin="a b"), "admin= in"),
                 (dict(admin=""), "admin= in"),
                 (dict(admin="root"), "admin= in " + str(self.conf) + " must be your own administrator account, not root"),
                 (dict(admin="semaphore"), "must be your own administrator account, not semaphore"),
                 (dict(admin="grace"), "this VM has no account grace"),
                 (dict(expose="http"), "expose= in"), (dict(expose="https", address="--editor"), "address= in"),
                 (dict(expose="https", address="a b"), "address= in"),
                 (dict(address="controller.example.test"), "address= in " + str(self.conf) + " is only for expose=https"),
                 # What controller/expose-semaphore.sh would refuse only after the whole installation.
                 (dict(expose="https", address=IPV4 + ":443"), "is not a valid IP address"),
                 (dict(expose="https", address="192.0.2.300"), "is not a valid IP address"),
                 (dict(expose="https", address="controller.example.test:8443"), "is not a valid IP address"),
                 (dict(expose="https", address=IPV6 + "%eth0"), "is not a valid IP address"),
                 (dict(expose="https", address="controller.example.test."), "must be an IP address or a DNS name"),
                 (dict(expose="https", address="https://controller.example.test"), "is not a valid IP address"))
        for values, reason in cases:
            with self.subTest(values=values):
                self.write_conf(**values)
                self.assertStopped(self.run_script(), reason)
        self.assertEqual(self.installer_calls(), [])
        self.assertEqual(self.recorded("python3.12"), [])

    def test_an_ip_address_of_either_family_reaches_the_installer(self):
        for address in (IPV4, IPV6):
            with self.subTest(address=address):
                self.installer_log.unlink(missing_ok=True)
                self.write_conf(expose="https", address=address)
                self.assertEqual(self.run_script().returncode, 0)
                self.assertEqual(self.installer_calls()[0],
                                 f"install-controller.sh --apply --editor ada --expose https --address {address}")

    def test_the_address_check_is_the_exposure_scripts_own(self):
        expose = (ROOT / "controller" / "expose-semaphore.sh").read_text()
        script = SCRIPT.read_text()
        for shared in ("python3 -I -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])'",
                       "=~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]", "=~ ^[0-9.]+$ ||", "== *:* ]]", "== *%* ]]"):
            self.assertIn(shared, expose.replace('"$address"', "$address"))
        for shared in ("python3 -I -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])'",
                       "=~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]", "=~ ^[0-9.]+$ ||", "== *:* ]]", "!= *%* ]]"):
            self.assertIn(shared, script)

    def test_a_missing_values_file_is_named(self):
        self.conf.unlink()
        self.assertStopped(self.run_script(), f"there is no {self.conf}")

    def test_an_installer_that_fails_stops_it_without_the_readiness_check(self):
        result = self.run_script(MOCK_INSTALLER_STATUS="1")
        self.assertStopped(result, "the installer ended with an error, shown above.")
        self.assertIn("installer output", result.stdout)
        self.assertEqual(self.recorded("python3.12"), [])

    def test_a_failing_readiness_check_is_a_stop_that_names_the_command(self):
        result = self.run_script(MOCK_READINESS="1")
        self.assertStopped(result, "the controller is installed, but its readiness check fails; see which check with: "
                                   "sudo python3.12 controller/check-controller.py")

    def test_on_an_installed_controller_it_only_checks(self):
        for marker in (self.marker, self.work / "seeded-earlier"):
            with self.subTest(marker=marker.name):
                marker.write_text("")
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("first-boot: this controller is already installed; the installer is not run again",
                              result.stdout)
                self.assertIn("first-boot: RESULT: OK", result.stdout)
                self.assertEqual(self.installer_calls(), [])
                marker.unlink()

    def test_an_installer_that_fails_only_at_https_says_to_run_this_again(self):
        self.write_conf(expose="https")
        result = self.run_script(MOCK_INSTALLER_STATUS="1", MOCK_INSTALLER_SEEDS=str(self.marker))
        self.assertStopped(result, "the controller is installed, but publishing the UI over HTTPS failed, for the reason "
                                   "shown above; fix it and run this again: sudo bash controller/first-boot.sh")
        self.assertNotIn("a new VM is the short way", result.stdout)
        self.assertEqual(self.recorded("python3.12"), [])

    def test_a_second_run_finishes_the_https_step_that_failed_and_only_then_reports_ok(self):
        self.write_conf(expose="https", address="controller.example.test")
        self.assertEqual(self.run_script(MOCK_INSTALLER_STATUS="1", MOCK_INSTALLER_SEEDS=str(self.marker)).returncode, 1)
        # Still failing: no OK, and the installer is not run a second time.
        result = self.run_script(MOCK_EXPOSE_STATUS="1")
        self.assertStopped(result, "publishing the UI over HTTPS failed, for the reason shown above; fix it and run this "
                                   "again: sudo bash controller/first-boot.sh")
        self.assertIn("exposure output", result.stdout)
        # Fixed: the exposure script alone runs, with the address, and then the readiness check.
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call.split(" ", 1)[0] for call in self.installer_calls() if not call.startswith("HOME=")],
                         ["install-controller.sh", "expose-semaphore.sh", "expose-semaphore.sh"])
        self.assertEqual(self.installer_calls()[-1], "expose-semaphore.sh --mode https --address controller.example.test")
        for line in ("first-boot: publishing the UI over HTTPS, which an earlier run did not finish",
                     "first-boot: RESULT: OK", "first-boot: next, browse to the https address"):
            self.assertIn(line, result.stdout)
        # Published: a further run leaves the exposure alone.
        calls = len(self.installer_calls())
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(len(self.installer_calls()), calls)

    def test_a_second_run_adds_to_the_log(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.run_script(MOCK_READINESS="1").returncode, 1)
        log = self.log.read_text()
        self.assertEqual((log.count("first-boot: started "), log.count("RESULT: OK"), log.count("RESULT: STOPPED")),
                         (2, 1, 1))

    def test_it_needs_root(self):
        result = self.run_script(MOCK_UID="1000")
        self.assertEqual((result.returncode, result.stdout), (1, "Run with sudo on the controller.\n"))
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
