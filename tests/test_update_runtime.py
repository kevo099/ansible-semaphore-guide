"""Offline runs of controller/update-runtime.sh on a temporary controller; no package index, service or root."""

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PINS = (ROOT / "requirements-controller.txt").read_text()
# What a controller installed from v1.1.0 or v1.2.0 holds: four packages older than the pins.
OLD_FREEZE = textwrap.dedent("""\
    ansible-core==2.20.8
    cffi==2.1.1
    cryptography==50.0.2
    Jinja2==3.1.6
    MarkupSafe==3.0.2
    packaging==26.3
    pycparser==2.23
    PyYAML==6.0.3
    resolvelib==1.2.1
    """)
CURRENT_FREEZE = "".join(line + "\n" for line in PINS.splitlines() if line and not line.startswith("#"))
OLD_ARGS = "-o UserKnownHostsFile=/etc/semaphore/known_hosts -o StrictHostKeyChecking=yes"
REUSE = "-o ControlMaster=auto -o ControlPersist=60s "

MOCK_PIP = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

state, log = Path(os.environ["MOCK_FREEZE"]), Path(os.environ["MOCK_LOG"])
args = [a for a in sys.argv[1:] if a != "--disable-pip-version-check"]
with log.open("a") as stream:
    stream.write(json.dumps(["pip", *args, f"umask={os.umask(0):03o}"]) + "\n")


def read(path):
    found = {}
    for line in Path(path).read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, version = line.split("==")
            found[name.lower()] = (name, version)
    return found


if args[0] == "freeze":
    sys.stdout.write(state.read_text())
elif args[0] == "install":
    counter = Path(str(log) + ".installs")
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    if str(count) in os.environ.get("MOCK_PIP_FAILS", "").split(","):
        sys.exit(1)
    have = read(state)
    have.update(read(args[args.index("--requirement") + 1]))
    if os.environ.get("MOCK_PIP_KEEPS"):
        have[os.environ["MOCK_PIP_KEEPS"].lower()] = (os.environ["MOCK_PIP_KEEPS"], "0")
    state.write_text("".join(f"{name}=={version}\n" for name, version in have.values()))
'''

MOCK_COMMAND = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

name, args = Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a") as stream:
    stream.write(json.dumps([name, *args]) + "\n")
if name == "id":
    print(os.environ.get("MOCK_UID", "0"))
elif name == "pgrep":
    sys.exit(0 if os.environ.get("MOCK_TASK_RUNNING") else 1)
elif name == "systemctl" and args[0] == "is-active":
    sys.exit(3 if os.environ.get("MOCK_SEMAPHORE_STOPPED") else 0)
elif name == "python3.12":
    failed = int(os.environ.get("MOCK_READINESS", "0"))
    print(json.dumps({"passed": not failed, "checks": {"http_ping": True, "ansible_is_available": not failed}}))
    sys.exit(failed)
'''


class UpdateRuntimeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.venv = self.work / "ansible-venv"
        (self.venv / "bin").mkdir(parents=True)
        pip = self.venv / "bin" / "pip"
        pip.write_text(MOCK_PIP)
        pip.chmod(0o755)
        self.freeze = self.work / "freeze.txt"
        self.freeze.write_text(OLD_FREEZE)
        self.etc = self.work / "etc-semaphore"
        self.etc.mkdir()
        self.config = self.etc / "config.json"
        self.write_config(OLD_ARGS)
        self.saved = self.work / "saved"
        self.log = self.work / "commands.jsonl"
        self.log.touch()
        self.bin = self.work / "bin"
        self.bin.mkdir()
        for name in ("id", "pgrep", "systemctl", "chown", "curl", "sleep", "python3.12"):
            (self.bin / name).write_text(MOCK_COMMAND)
            (self.bin / name).chmod(0o755)
        # Only the filesystem locations are relocated; the script's own logic runs.
        self.repo = self.work / "guide"
        (self.repo / "controller").mkdir(parents=True)
        (self.repo / "requirements-controller.txt").write_text(PINS)
        script = (ROOT / "controller" / "update-runtime.sh").read_text()
        for original, replacement in (("/opt/ansible-venv", self.venv), ("/etc/semaphore", self.etc),
                                      ("/root/ansible-lab-update", self.saved)):
            script = script.replace(original, str(replacement))
        self.script = self.repo / "controller" / "update-runtime.sh"
        self.script.write_text(script)

    def write_config(self, arguments, **extra):
        env_vars = {"PATH": "/usr/bin", **({"ANSIBLE_SSH_ARGS": arguments} if arguments is not None else {})}
        self.config.write_text(json.dumps({"interface": "127.0.0.1", "cookie_hash": "kept", "env_vars": env_vars,
                                           **extra}, indent=2) + "\n")
        self.config.chmod(0o640)

    def run_script(self, *arguments, **environment):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", MOCK_LOG=str(self.log),
                   MOCK_FREEZE=str(self.freeze), **environment)
        return subprocess.run(["bash", str(self.script), *arguments], env=env, capture_output=True, text=True, timeout=60)

    def commands(self, name=None):
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [call for call in calls if name is None or call[0] == name]

    def ssh_arguments(self):
        return json.loads(self.config.read_text())["env_vars"].get("ANSIBLE_SSH_ARGS")

    def test_the_plan_lists_what_is_older_and_changes_nothing(self):
        before = (self.freeze.read_text(), self.config.read_text())
        for arguments in ((), ("--plan",)):
            with self.subTest(arguments=arguments):
                result = self.run_script(*arguments)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("packages to install at the pinned version: 4\n    ansible-core 2.20.8 -> 2.21.4\n",
                              result.stdout)
                for line in ("    cryptography 50.0.2 -> 50.0.1", "    MarkupSafe 3.0.2 -> 3.0.3",
                             "    pycparser 2.23 -> 3.0",
                             f"  SSH connection reuse for Semaphore jobs: to add to ANSIBLE_SSH_ARGS in {self.config}.",
                             "Plan only. Run again with --apply"):
                    self.assertIn(line, result.stdout)
                self.assertEqual((self.freeze.read_text(), self.config.read_text()), before)
                self.assertEqual(self.commands("systemctl"), [])
                self.assertFalse(self.saved.exists())

    def test_apply_updates_both_with_semaphore_stopped_and_checks_readiness(self):
        config_before = self.config.read_text()
        result = self.run_script("--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.freeze.read_text().lower(), CURRENT_FREEZE.lower())
        self.assertEqual(self.ssh_arguments(), REUSE + OLD_ARGS)
        after = json.loads(self.config.read_text())
        self.assertEqual((after["cookie_hash"], after["env_vars"]["PATH"]), ("kept", "/usr/bin"))
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assertIn(["chown", "root:semaphore", str(self.config)], self.commands("chown"))
        # Stopped before anything changes, started after everything has.
        order = [call[:3] for call in self.commands() if call[0] in ("systemctl", "pip", "python3.12")
                 and call[1] != "freeze" and call[1:] != ["is-active", "--quiet", "semaphore"]]
        self.assertEqual([call[:2] for call in order], [["systemctl", "stop"], ["pip", "install"],
                                                        ["systemctl", "start"], ["python3.12", order[-1][1]]])
        self.assertTrue(order[-1][1].endswith("controller/check-controller.py"))
        # pip writes files the service must read: not with this script's private umask.
        install = [call for call in self.commands("pip") if call[1] == "install"]
        self.assertEqual([call[-1] for call in install], ["umask=022"])
        self.assertEqual(install[0][1:4], ["install", "--requirement", str(self.repo / "requirements-controller.txt")])
        # What was there before is saved root-only.
        self.assertEqual(stat.S_IMODE(self.saved.stat().st_mode), 0o700)
        saved = sorted(self.saved.iterdir())
        self.assertEqual([path.name.split("-before-")[0] for path in saved], ["ansible-venv", "semaphore-config"])
        self.assertEqual(saved[0].read_text(), OLD_FREEZE)
        self.assertEqual(saved[1].read_text(), config_before)
        for path in saved:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertIn("Ansible runtime updated: 4 package(s) are now at their pinned version.", result.stdout)
        self.assertEqual(result.stdout.splitlines()[-1], "Updated. The readiness check passed.")

        self.log.write_text("")
        for arguments in (("--apply",), ()):
            again = self.run_script(*arguments)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertEqual(again.stdout.splitlines()[-1], "Nothing to do: both match this copy of the guide.")
        self.assertEqual(self.commands("systemctl"), [])
        self.assertEqual(len(list(self.saved.iterdir())), 2)

    def test_only_what_is_older_changes(self):
        self.freeze.write_text(CURRENT_FREEZE)
        result = self.run_script("--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("every pinned package is at its pinned version", result.stdout)
        self.assertEqual([call for call in self.commands("pip") if call[1] == "install"], [])
        self.assertEqual(self.ssh_arguments(), REUSE + OLD_ARGS)
        self.assertEqual([path.name.split("-before-")[0] for path in self.saved.iterdir()], ["semaphore-config"])

        self.setUp()
        self.write_config(REUSE + OLD_ARGS)
        config_before = self.config.read_text()
        result = self.run_script("--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SSH connection reuse for Semaphore jobs: already set.", result.stdout)
        self.assertEqual(self.config.read_text(), config_before)
        self.assertEqual(self.freeze.read_text().lower(), CURRENT_FREEZE.lower())

    def test_a_running_task_stops_it_unless_forced(self):
        before = (self.freeze.read_text(), self.config.read_text())
        result = self.run_script("--apply", MOCK_TASK_RUNNING="1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("A Semaphore task is running", result.stdout)
        self.assertIn("Nothing was changed", result.stdout)
        self.assertEqual((self.freeze.read_text(), self.config.read_text()), before)
        self.assertEqual([call for call in self.commands("systemctl") if call[1] in ("stop", "start")], [])
        self.assertIn(["pgrep", "-u", "semaphore", "-f", "ansible-playbook"], self.commands("pgrep"))
        # A plan never needs Semaphore stopped.
        self.assertEqual(self.run_script(MOCK_TASK_RUNNING="1").returncode, 0)
        forced = self.run_script("--apply", "--force", MOCK_TASK_RUNNING="1")
        self.assertEqual(forced.returncode, 0, forced.stdout + forced.stderr)
        self.assertEqual(self.ssh_arguments(), REUSE + OLD_ARGS)

    def test_a_failed_installation_puts_the_earlier_versions_back(self):
        config_before = self.config.read_text()
        result = self.run_script("--apply", MOCK_PIP_FAILS="1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Installing the pinned versions failed; installing the earlier versions again.", result.stdout)
        self.assertIn("The earlier versions are back. Nothing else was changed.", result.stdout)
        installs = [call for call in self.commands("pip") if call[1] == "install"]
        saved = next(self.saved.glob("ansible-venv-before-*.txt"))
        self.assertEqual([call[3] for call in installs], [str(self.repo / "requirements-controller.txt"), str(saved)])
        self.assertEqual(self.freeze.read_text(), OLD_FREEZE)
        self.assertEqual(self.config.read_text(), config_before)
        self.assertEqual([call[1] for call in self.commands("systemctl") if call[1] in ("stop", "start")], ["stop", "start"])

        self.setUp()
        result = self.run_script("--apply", MOCK_PIP_FAILS="1,2")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        saved = next(self.saved.glob("ansible-venv-before-*.txt"))
        self.assertIn(f"Could not put the earlier versions back. Once the cause is fixed, run:\n"
                      f"  sudo {self.venv}/bin/pip install --requirement {saved}\n", result.stdout)

    def test_a_package_pip_leaves_behind_is_reported(self):
        result = self.run_script("--apply", MOCK_PIP_KEEPS="pycparser")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("still not at their pinned version:\n  pycparser 0 (pinned 3.0)\n", result.stdout)
        self.assertEqual([call[1] for call in self.commands("systemctl") if call[1] in ("stop", "start")], ["stop", "start"])

    def test_packages_you_added_are_listed_and_kept(self):
        self.freeze.write_text(OLD_FREEZE + "pywinrm==0.5.0\nlocal-tool @ file:///srv/local-tool\n")
        result = self.run_script()
        self.assertIn("  Packages you added, kept as they are: 2\n    pywinrm\n    local-tool\n", result.stdout)
        result = self.run_script("--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("pywinrm==0.5.0\n", self.freeze.read_text())

    def test_a_configuration_of_another_form_is_left_alone(self):
        self.freeze.write_text(CURRENT_FREEZE)
        for arguments in (None, "-F /etc/semaphore/ssh_config"):
            with self.subTest(arguments=arguments):
                self.write_config(arguments)
                before = self.config.read_text()
                result = self.run_script("--apply")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("has no ANSIBLE_SSH_ARGS of the installer's form; left alone.", result.stdout)
                self.assertEqual(result.stdout.splitlines()[-1], "Nothing to do: both match this copy of the guide.")
                self.assertEqual(self.config.read_text(), before)

    def test_a_stopped_semaphore_stays_stopped(self):
        result = self.run_script("--apply", MOCK_SEMAPHORE_STOPPED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call[1] for call in self.commands("systemctl") if call[1] in ("stop", "start")], ["stop"])
        self.assertIn("is still stopped; start it with sudo systemctl start semaphore.", result.stdout)
        self.assertEqual(self.commands("python3.12"), [])

    def test_a_failing_readiness_check_ends_with_an_error(self):
        result = self.run_script("--apply", MOCK_READINESS="1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(result.stdout.endswith("Updated, but the readiness check does not pass:\n  ansible_is_available\n"
                                               "For all of it: sudo python3.12 controller/check-controller.py\n"),
                        result.stdout)

    def test_ansible_keeps_the_callers_locale(self):
        # Ansible refuses to start without a UTF-8 locale, and the readiness check runs it.
        self.assertNotIn("\nexport LC_ALL", self.script.read_text())

    def test_the_hint_is_short_and_silent_when_nothing_is_older(self):
        result = self.run_script("--hint")
        self.assertEqual((result.returncode, result.stdout), (0, textwrap.dedent("""\
            Also older than this copy of the guide, and left alone by update-controller.sh:
              Ansible runtime /opt/ansible-venv: 2.20.8 installed, 2.21.4 pinned
              SSH connection reuse for Semaphore jobs: not set
            To see and apply those: sudo bash controller/update-runtime.sh
            """).replace("/opt/ansible-venv", str(self.venv))))
        self.freeze.write_text(CURRENT_FREEZE)
        self.write_config(REUSE + OLD_ARGS)
        self.assertEqual((self.run_script("--hint").returncode, self.run_script("--hint").stdout), (0, ""))
        # A controller built by hand has neither file: nothing to say, and no error.
        self.config.unlink()
        result = self.run_script("--hint")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertEqual(self.commands("systemctl"), [])

    def test_it_needs_root_a_made_controller_and_known_options(self):
        result = self.run_script(MOCK_UID="1000")
        self.assertEqual((result.returncode, result.stderr), (1, "Run it with sudo on the controller.\n"))
        self.assertEqual(self.run_script("--apply", "--plan").returncode, 2)
        self.assertEqual(self.run_script("--runtime").returncode, 2)
        self.assertIn("Usage: sudo bash controller/update-runtime.sh", self.run_script("--help").stdout)
        self.config.unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("this controller was not made by the guide's installer", result.stdout)

    def test_the_pins_are_all_of_the_form_it_reads(self):
        (self.repo / "requirements-controller.txt").write_text(PINS + "ansible-core>=2.21\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("has a line this script cannot read: ansible-core>=2.21", result.stderr)


class UpdateControllerHintTests(unittest.TestCase):
    """controller/update-controller.sh names the runtime after a plan or an update, and keeps its own result."""

    def run_wrapper(self, status):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        work = Path(directory.name)
        (work / "controller").mkdir()
        wrapper = work / "controller" / "update-controller.sh"
        wrapper.write_text((ROOT / "controller" / "update-controller.sh").read_text())
        (work / "controller" / "update-runtime.sh").write_text('echo "runtime $*"\n')
        (work / "bin").mkdir()
        for name, body in (("id", "echo 0"), ("python3.12", f'echo "tool $2"; exit {status}')):
            (work / "bin" / name).write_text(f"#!/bin/sh\n{body}\n")
            (work / "bin" / name).chmod(0o755)
        return subprocess.run(["bash", str(wrapper), "--apply"], capture_output=True, text=True, timeout=60,
                              env=dict(os.environ, PATH=f"{work / 'bin'}:{os.environ['PATH']}"))

    def test_the_hint_follows_a_plan_or_an_update_and_never_changes_the_status(self):
        for status, hinted in ((0, True), (1, True), (2, False), (130, False)):
            with self.subTest(status=status):
                result = self.run_wrapper(status)
                self.assertEqual(result.returncode, status)
                self.assertEqual(result.stdout, "tool --apply\n" + ("runtime --hint\n" if hinted else ""))


if __name__ == "__main__":
    unittest.main()
