"""Offline installer safety checks; no test installs packages or starts services."""

import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = ("install-controller.sh", "install-controller-el9.sh")
COMMON = ROOT / "scripts" / "controller-common.sh"


class InstallerPlanTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.commands = self.work / "commands"
        self.commands.mkdir()
        self.log = self.work / "unexpected-commands"
        # A plan must stop before invoking any command that could change the VM,
        # contact the network or load a helper which might do either.
        for command in ("apt-get", "dnf", "curl", "install", "mkdir", "cp", "chmod",
                        "chown", "rm", "tar", "useradd", "systemctl", "git", "ssh-keygen",
                        "runuser", "restorecon", "setfacl", "python3", "python3.12"):
            executable = self.commands / command
            executable.write_text('#!/bin/bash\nprintf "%s\\n" "$0" >> "$COMMAND_LOG"\nexit 97\n')
            executable.chmod(0o755)
        self.environment = {
            **os.environ,
            "PATH": str(self.commands) + os.pathsep + os.environ["PATH"],
            "COMMAND_LOG": str(self.log),
            "SUDO_USER": "",
        }

    def run_installer(self, installer, *arguments):
        result = subprocess.run(["/bin/bash", str(ROOT / "scripts" / installer), *arguments],
                                cwd=self.work, env=self.environment,
                                capture_output=True, text=True, timeout=10)
        self.assertFalse(self.log.exists(), self.log.read_text() if self.log.exists() else "")
        return result

    def test_default_and_explicit_plan_are_read_only_and_describe_local_seeding(self):
        for installer in INSTALLERS:
            for arguments in ((), ("--plan",),
                              ("--plan", "--editor", "labeditor", "--lab-dir",
                               str(self.work / "unused-lab"), "--expose", "https"),
                              ("--editor", "labeditor", "--expose", "http"),
                              ("--expose", "https", "--address", "controller.example.test")):
                with self.subTest(installer=installer, arguments=arguments):
                    result = self.run_installer(installer, *arguments)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertRegex(result.stdout, r"(?m)^Plan:")
                    self.assertIn("22 scoped task templates", result.stdout)
                    self.assertIn("local folder", result.stdout)
                    self.assertFalse((self.work / "unused-lab").exists())

    def test_invalid_options_fail_before_any_installation(self):
        for installer in INSTALLERS:
            for arguments in (("--unknown",), ("--editor",), ("--lab-dir",),
                              ("--editor", ""), ("--lab-dir", ""),
                              ("--editor", "--apply"), ("--lab-dir", "--apply"),
                              ("--plan", "--apply"), ("--apply", "--plan"),
                              ("--expose",), ("--expose", "ftp"),
                              ("--address",), ("--expose", "https", "--address", ""),
                              ("--expose", "https", "--address", "--apply"),
                              ("--address", "controller.example.test"),
                              ("--apply", "--editor", "labeditor", "--address", "controller.example.test")):
                with self.subTest(installer=installer, arguments=arguments):
                    result = self.run_installer(installer, *arguments)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("Usage:", result.stdout)

    def test_address_without_expose_says_why_it_is_refused(self):
        for installer in INSTALLERS:
            with self.subTest(installer=installer):
                result = self.run_installer(installer, "--address", "controller.example.test")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("Pass --address together with --expose.", result.stdout)

    def test_apply_refuses_non_root_before_os_checks_or_mutations(self):
        executable = self.commands / "id"
        executable.write_text("#!/bin/bash\nprintf '1000\\n'\n")
        executable.chmod(0o755)
        for installer in INSTALLERS:
            with self.subTest(installer=installer):
                result = self.run_installer(installer, "--apply", "--editor", "labeditor")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("sudo", result.stdout)

    def test_apply_refuses_unsupported_os_before_any_mutations(self):
        executable = self.commands / "id"
        executable.write_text("#!/bin/bash\nprintf '0\\n'\n")
        executable.chmod(0o755)
        startup = self.work / "fake-os.sh"
        startup.write_text('''source() {
  if [[ "$1" == /etc/os-release ]]; then
    ID=$TEST_OS_ID; VERSION_ID=$TEST_OS_VERSION
  else
    builtin source "$@"
  fi
}
''')
        self.environment["BASH_ENV"] = str(startup)
        for installer, distribution, version in (("install-controller.sh", "debian", "12"),
                                                   ("install-controller.sh", "ubuntu", "22.04"),
                                                   ("install-controller-el9.sh", "ubuntu", "24.04"),
                                                   ("install-controller-el9.sh", "rocky", "9.3")):
            with self.subTest(installer=installer, distribution=distribution, version=version):
                self.environment.update(TEST_OS_ID=distribution, TEST_OS_VERSION=version)
                result = self.run_installer(installer, "--apply", "--editor", "labeditor")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("Requires", result.stdout)


class InlinePythonTests(unittest.TestCase):
    """The shell scripts run as root, from whatever folder the operator is in."""

    def test_inline_python_runs_isolated(self):
        # -I leaves the working directory and the PYTHON* variables out, so a module file
        # there cannot stand in for one the snippet imports.
        scripts = set()
        for script in sorted((ROOT / "scripts").glob("*.sh")):
            for match in re.finditer(r"\bpython3(?:\.\d+)?((?: -\w+)*) (?:-c|-)(?=\s)", script.read_text()):
                scripts.add(script.name)
                with self.subTest(script=script.name, command=match.group(0)):
                    self.assertIn("-I", match.group(1).split())
        self.assertEqual(scripts, {"add-target.sh", "expose-semaphore.sh", *INSTALLERS})


class SharedPreflightTests(unittest.TestCase):
    def run_helper(self, body, *arguments):
        return subprocess.run(["/bin/bash", "-c", 'set -euo pipefail; source "$1"; shift; ' + body,
                               "controller-test", str(COMMON), *arguments],
                              capture_output=True, text=True, timeout=10)

    def test_parser_preserves_defaults_and_requested_lab_settings(self):
        body = '''
usage() { :; }
SUDO_USER=sudoeditor
controller_parse_args "$@"
printf '%s\\n' "$mode" "$editor" "$lab_dir" "$expose" "$expose_address"
'''
        for arguments, expected in (((), ["--plan", "sudoeditor", "/opt/ansible-lab", "", ""]),
                                    (("--apply", "--editor", "labeditor", "--lab-dir", "/srv/lab",
                                      "--expose", "https"), ["--apply", "labeditor", "/srv/lab", "https", ""]),
                                    (("--address", "controller.example.test", "--apply", "--expose", "http"),
                                     ["--apply", "sudoeditor", "/opt/ansible-lab", "http",
                                      "controller.example.test"])):
            with self.subTest(arguments=arguments):
                result = self.run_helper(body, *arguments)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)

    def validate_lab(self, path, editor="labeditor", parent_access=True):
        # Account/permission lookups are simulated, while realpath performs real
        # normalization. The tests need neither root nor those accounts to exist.
        body = '''
lab_dir=$1; editor=$2
runuser() { [[ "$PARENT_ACCESS" == yes ]]; }
getent() { [[ "$1" == passwd && "$2" == labeditor ]]; }
PARENT_ACCESS=$3
controller_validate_lab
printf 'LAB=%s\\n' "$lab_dir"
'''
        return self.run_helper(body, path, editor, "yes" if parent_access else "no")

    def test_rejects_service_inaccessible_paths_after_normalization(self):
        blocked = ("/home", "/root", "/run/user", "/tmp", "/var/tmp", "/var/lib/semaphore")
        for prefix in blocked:
            for path in (prefix, prefix + "/lab", "/srv/.." + prefix + "/lab"):
                with self.subTest(path=path):
                    result = self.validate_lab(path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("cannot read", result.stdout)

    def test_rejects_relative_and_filesystem_root_paths(self):
        for path in ("lab", "./lab", "/", "/srv/.."):
            with self.subTest(path=path):
                result = self.validate_lab(path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("lab folder", result.stdout)

    def test_normalizes_allowed_paths(self):
        for path in ("/opt/ansible-lab/", "/opt/example/../ansible-lab"):
            with self.subTest(path=path):
                result = self.validate_lab(path)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("LAB=/opt/ansible-lab", result.stdout)

    def test_rejects_missing_editor_and_inaccessible_parent(self):
        for editor in ("", "root", "semaphore", "missing-editor"):
            with self.subTest(editor=editor):
                result = self.validate_lab("/opt/ansible-lab", editor=editor)
                self.assertNotEqual(result.returncode, 0)
        result = self.validate_lab("/opt/ansible-lab", parent_access=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("permissions", result.stdout)

    def test_existing_lab_and_dangling_symlink_refuse_fresh_install(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lab"
            for dangling in (False, True):
                with self.subTest(dangling_symlink=dangling):
                    if dangling:
                        path.symlink_to(Path(directory) / "missing")
                    else:
                        path.mkdir()
                    result = self.run_helper('lab_dir=$1; controller_require_fresh_state', str(path))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("Existing state:", result.stdout)
                    if dangling:
                        self.assertTrue(path.is_symlink())
                        path.unlink()
                    else:
                        self.assertTrue(path.is_dir())
                        path.rmdir()


class SharedDownloadTests(unittest.TestCase):
    def test_checksum_mismatch_deletes_download_before_extracting(self):
        # All commands that could touch /var/cache are replaced. The real
        # pipeline and failure branch execute, including their command ordering.
        body = '''
set -euo pipefail
source "$1"
install() { printf 'CACHE_CREATED\\n'; }
curl() { printf 'DOWNLOAD_REQUESTED\\n'; }
sha256sum() { cat >/dev/null; return 1; }
rm() { printf 'REMOVED %s\\n' "$*"; }
tar() { printf 'UNSAFE_EXTRACTION\\n'; return 99; }
controller_download
printf 'UNSAFE_CONTINUATION\\n'
'''
        result = subprocess.run(["/bin/bash", "-c", body, "controller-test", str(COMMON)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("DOWNLOAD_REQUESTED", result.stdout)
        self.assertIn("REMOVED -f -- /var/cache/ansible-semaphore-guide/", result.stdout)
        self.assertIn("SHA-256 mismatch", result.stdout)
        self.assertNotIn("UNSAFE", result.stdout)


class SharedPackageTests(unittest.TestCase):
    """Ubuntu package steps with apt-get and sleep simulated; nothing is installed."""

    def run_common(self, body, *arguments, common=COMMON):
        return subprocess.run(["/bin/bash", "-c", 'set -euo pipefail; source "$1"; shift; ' + body,
                               "controller-test", str(common), *arguments],
                              capture_output=True, text=True, timeout=20)

    def apt_update(self, failures):
        body = '''
failures=$1 calls=0
apt-get() { printf 'APT %s\\n' "$*"; (( ++calls > failures )); }
sleep() { printf 'SLEEP %s\\n' "$*"; }
controller_apt_update
printf 'CONTINUED\\n'
'''
        return self.run_common(body, str(failures))

    def test_apt_update_is_retried_while_another_apt_process_holds_its_lock(self):
        result = self.apt_update(failures=2)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines.count("APT update"), 3)
        self.assertEqual(lines.count("SLEEP 10"), 2)
        self.assertIn("another apt process may hold its lock", result.stdout)
        self.assertEqual(lines[-1], "CONTINUED")

    def test_apt_update_gives_up_after_thirty_attempts(self):
        result = self.apt_update(failures=1000)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines.count("APT update"), 30)
        self.assertEqual(lines.count("SLEEP 10"), 29)
        self.assertIn("failed 30 times", result.stdout)
        self.assertNotIn("CONTINUED", result.stdout)

    def test_failed_postgresql_install_removes_the_new_runtime_unless_it_created_state(self):
        body = '''
apt_status=$1
apt-get() { printf 'APT %s\\n' "$*"; return "$apt_status"; }
controller_apt_install_postgresql
printf 'CONTINUED\\n'
'''
        for apt_status, state in ((0, None), (100, None), (100, "etc/postgresql"), (100, "var/lib/postgresql")):
            with self.subTest(apt_status=apt_status, state=state), tempfile.TemporaryDirectory() as directory:
                # Only the paths move into the test folder; the function's logic runs unchanged.
                root = Path(directory)
                text = COMMON.read_text()
                for path in ("/etc/postgresql", "/var/lib/postgresql", "/opt/ansible-venv"):
                    text = text.replace(path, directory + path)
                common = root / "controller-common.sh"
                common.write_text(text)
                runtime = root / "opt" / "ansible-venv"
                (runtime / "bin").mkdir(parents=True)
                if state:
                    (root / state).mkdir(parents=True)
                result = self.run_common(body, str(apt_status), common=common)
                self.assertIn("APT -o DPkg::Lock::Timeout=600 install -y postgresql-16", result.stdout)
                if apt_status == 0:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("CONTINUED", result.stdout)
                    self.assertTrue(runtime.is_dir())
                    continue
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn("CONTINUED", result.stdout)
                self.assertIn("Installing PostgreSQL 16 failed", result.stdout)
                if state:
                    # A rerun is refused anyway, so the runtime stays for the manual recovery.
                    self.assertTrue(runtime.is_dir())
                    self.assertIn("refuses to run again", result.stdout)
                else:
                    self.assertFalse(runtime.exists())
                    self.assertIn("rerun --apply", result.stdout)

    def test_ubuntu_installer_apt_get_waits_for_the_dpkg_lock(self):
        # apt-get gives up at once on a held dpkg lock unless DPkg::Lock::Timeout is set,
        # and apt-get update takes another lock, so only the retrying helper runs it.
        invocations = []
        for script in ("install-controller.sh", "controller-common.sh"):
            for line in (ROOT / "scripts" / script).read_text().splitlines():
                command = line.strip().removeprefix("if ")
                if command.startswith("apt-get "):
                    invocations.append(command)
        self.assertEqual(len(invocations), 4, invocations)
        for command in invocations:
            with self.subTest(command=command):
                if command.startswith("apt-get update"):
                    self.assertEqual(command, "apt-get update; then return; fi")
                else:
                    self.assertTrue(command.startswith("apt-get -o DPkg::Lock::Timeout=600 install -y "))


class SharedFinishTests(unittest.TestCase):
    """The optional exposure step, with expose-semaphore.sh and the readiness check simulated."""

    def finish(self, expose="", address="", expose_status=0, check_status=0):
        with tempfile.TemporaryDirectory() as directory:
            scripts = Path(directory) / "scripts"
            scripts.mkdir()
            calls = Path(directory) / "calls"
            (scripts / "expose-semaphore.sh").write_text(
                'printf "EXPOSE %s\\n" "$*" >> "$CALL_LOG"\nexit "$EXPOSE_STATUS"\n')
            body = '''
script_dir=$1 expose=$2 expose_address=$3 lab_dir=/opt/ansible-lab editor=labeditor
python3.12() { printf 'CHECK %s\\n' "$*" >> "$CALL_LOG"; return "$CHECK_STATUS"; }
controller_finish
printf 'FINISHED\\n'
'''
            result = subprocess.run(["/bin/bash", "-c", 'set -euo pipefail; source "$1"; shift; ' + body,
                                     "controller-test", str(COMMON), str(scripts), expose, address],
                                    env={**os.environ, "CALL_LOG": str(calls), "EXPOSE_STATUS": str(expose_status),
                                         "CHECK_STATUS": str(check_status)},
                                    capture_output=True, text=True, timeout=10)
            return result, calls.read_text().splitlines() if calls.exists() else [], str(scripts)

    def test_exposure_gets_the_address_and_the_readiness_check(self):
        for expose, address, arguments in (("https", "controller.example.test",
                                            "--mode https --address controller.example.test"),
                                           ("http", "", "--mode http")):
            with self.subTest(expose=expose, address=address):
                result, calls, scripts = self.finish(expose, address)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(calls, [f"EXPOSE {arguments}", f"CHECK {scripts}/check-controller.py"])
                self.assertIn("Controller installed and seeded.", result.stdout)
                self.assertNotIn("failed", result.stdout)
                self.assertIn("FINISHED", result.stdout)

    def test_without_expose_nothing_is_published(self):
        result, calls, _scripts = self.finish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(calls, [])
        self.assertIn("Controller installed and seeded.", result.stdout)

    def test_failed_exposure_ends_with_next_steps_and_only_the_exposure_command(self):
        for expose_status, check_status, expected_calls in ((100, 0, 1), (0, 1, 2)):
            with self.subTest(expose_status=expose_status, check_status=check_status):
                result, calls, scripts = self.finish("https", "controller.example.test",
                                                     expose_status, check_status)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(len(calls), expected_calls)
                self.assertNotIn("FINISHED", result.stdout)
                # The next steps still print, and the last lines name the one step to repeat.
                self.assertIn("Controller installed and seeded.", result.stdout)
                self.assertIn("Automation public key: /etc/semaphore/svc_ansible.pub", result.stdout)
                self.assertIn("Only the --expose https step failed. Do not run the installer again",
                              result.stdout)
                self.assertEqual(result.stdout.splitlines()[-2:], [
                    f"  sudo bash {scripts}/expose-semaphore.sh --mode https --address controller.example.test",
                    f"  sudo python3.12 {scripts}/check-controller.py"])


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class SharedLabTests(unittest.TestCase):
    def populate(self, directory, family="deb", readable=True):
        lab = Path(directory) / "lab"
        # Only files in this disposable lab are created. Service-account changes,
        # private-key creation, SELinux relabeling and API calls are simulated.
        # Git and the file copying/modes execute normally as the test runner.
        body = '''
set -euo pipefail
umask 077
source "$1"
repo_dir=$2; script_dir=$repo_dir/scripts; lab_dir=$3
controller_family=$4; SERVICE_READABLE=$5; editor=labeditor
ssh-keygen() { :; }
chmod() {
  case "${*: -1}" in
    /etc/semaphore/svc_ansible|/etc/semaphore/svc_ansible.pub) ;;
    "$lab_dir"|"$lab_dir"/*) command chmod "$@" ;;
    *) echo 'Unexpected chmod outside the test lab' >&2; return 99 ;;
  esac
}
install() {
  local arguments=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -o|-g) shift 2 ;;
      *) arguments+=("$1"); shift ;;
    esac
  done
  case "${arguments[-1]}" in
    "$lab_dir"|"$lab_dir"/*) command install "${arguments[@]}" ;;
    *) echo 'Unexpected install outside the test lab' >&2; return 99 ;;
  esac
}
chown() { :; }
runuser() {
  if [[ "$2" == semaphore && "$SERVICE_READABLE" == no ]]; then return 1; fi
  shift 3
  "$@"
}
restorecon() { printf 'SELINUX_RELABELED\\n'; }
python3.12() {
  [[ "$1" == "$script_dir/seed-semaphore.py" ]] || return 99
  printf 'API_SEED_CALLED\\n'
  printf 'ARG=%s\\n' "$@"
}
controller_seed_lab
'''
        result = subprocess.run(["/bin/bash", "-c", body, "controller-test", str(COMMON),
                                 str(ROOT), str(lab), family, "yes" if readable else "no"],
                                env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
                                     "GIT_CONFIG_GLOBAL": "/dev/null"},
                                capture_output=True, text=True, timeout=20)
        return result, lab

    def test_both_families_populate_readable_local_repository_and_empty_inventory(self):
        for family in ("deb", "el"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory:
                result, lab = self.populate(directory, family)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("API_SEED_CALLED", result.stdout)
                self.assertIn(f"ARG={lab}", result.stdout)
                self.assertEqual("SELINUX_RELABELED" in result.stdout, family == "el")
                inventory = (lab / "inventories" / "lab.ini").read_text()
                active_lines = [line for line in inventory.splitlines() if line and not line.startswith("#")]
                self.assertEqual(active_lines, ["[ubuntu]", "[enterprise_linux]", "[lab:children]",
                                                "ubuntu", "enterprise_linux", "[lab:vars]",
                                                "ansible_user=svc_ansible",
                                                "ansible_python_interpreter=/usr/bin/python3"])
                for relative in ("ansible.cfg", "playbooks/stig-audit.yml", "playbooks/stig-apply.yml",
                                 "playbooks/tasks/stig_scan.yml", "scripts/summarize_xccdf.py"):
                    self.assertEqual((lab / relative).read_bytes(), (ROOT / relative).read_bytes())
                for path in [lab, *lab.rglob("*")]:
                    with self.subTest(path=path.relative_to(lab)):
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o2750 if path.is_dir() else 0o640)
                tracked = subprocess.run(["git", "-C", str(lab), "ls-files"],
                                         capture_output=True, text=True, check=True).stdout.splitlines()
                self.assertIn("scripts/summarize_xccdf.py", tracked)
                self.assertNotIn("inventories/lab.ini", tracked)
                ignored = subprocess.run(["git", "-C", str(lab), "check-ignore", "inventories/lab.ini",
                                          "host_vars/target.yml", "group_vars/lab.yml"],
                                         capture_output=True, text=True, check=True).stdout.splitlines()
                self.assertEqual(ignored, ["inventories/lab.ini", "host_vars/target.yml", "group_vars/lab.yml"])

    def test_unreadable_inventory_refuses_api_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.populate(directory, readable=False)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("cannot read", result.stdout)
            self.assertIn("Nothing was seeded", result.stdout)
            self.assertNotIn("API_SEED_CALLED", result.stdout)


if __name__ == "__main__":
    unittest.main()
