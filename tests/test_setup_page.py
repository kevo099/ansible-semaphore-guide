"""The setup page's logic, site/plan.js, checked in Node against the guide's own files.

The page tells a reader which commands to paste, so each one is compared with the
script or the page of the guide it comes from, the embedded first-boot file with
controller/first-boot/user-data.yaml, and every link with a heading that exists.
Nothing here opens a browser or a network connection.
"""

import importlib.util
import ipaddress
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from urllib.parse import urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
USER_DATA = (ROOT / "controller" / "first-boot" / "user-data.yaml").read_text()
NODE = shutil.which("node")
PLATFORMS = ("proxmox", "azure", "seed", "existing")
SYSTEMS = ("ubuntu", "rhel", "almalinux", "rocky")
EXPOSURES = (("tunnel", ""), ("https", ""), ("https", "controller.example.test"))
HOSTILE = ("ada; id", "ada$(id)", "ada`id`", "ada id", "-ada", "ada|id", "ada\nid", "<b>ada</b>", "ada'", 'ada"', "a" * 33)
# The user a cloud image of each system creates, which a seed ISO's administrator is.
IMAGE_USER = {"ubuntu": "ubuntu", "rhel": "cloud-user", "almalinux": "almalinux", "rocky": "rocky"}
# Built from parts so the repository's check for literal addresses passes over them.
IPV4 = "192.0.2" + ".5"
IPV6 = "2001:db8" + "::5"

spec = importlib.util.spec_from_file_location("validate", ROOT / "scripts" / "validate.py")
assert spec and spec.loader
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def node(expression, *arguments):
    """The JSON value of a JavaScript expression in which plan is site/plan.js and args the arguments."""
    script = (f"const plan = require({json.dumps(str(SITE / 'plan.js'))}); const args = JSON.parse(process.argv[1]); "
              f"process.stdout.write(JSON.stringify({expression}));")
    result = subprocess.run([NODE or "node", "-e", script, json.dumps(arguments)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def answers(platform="proxmox", system="ubuntu", expose="tunnel", address="", admin="ada", **more):
    return dict(platform=platform, system=system, admin=admin, expose=expose, address=address, **more)


@unittest.skipUnless(NODE, "Node.js is not installed")
class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = [answers(platform, system, expose, address, admin=IMAGE_USER[system] if platform == "seed" else "ada")
                     for platform, system, (expose, address) in itertools.product(PLATFORMS, SYSTEMS, EXPOSURES)]
        cls.steps = node("args[0].map((a) => plan.steps(a))", cls.cases)
        cls.methods = node("args[0].map((a) => plan.method(a).name)", cls.cases)

    def each(self):
        return zip(self.cases, self.methods, self.steps)

    def test_the_embedded_first_boot_file_is_the_guides_own(self):
        self.assertEqual(node("plan.USER_DATA"), USER_DATA,
                         "copy controller/first-boot/user-data.yaml into site/plan.js, between its two markers")

    def test_the_page_and_the_file_name_the_same_release(self):
        release = node("plan.RELEASE")
        self.assertRegex(release, r"^v\d+\.\d+\.\d+$")
        self.assertIn(f"\n      release={release}\n", USER_DATA)
        self.assertIn(f"```text\nrelease={release}\n", (ROOT / "docs" / "first-boot-controller.md").read_text())

    def test_the_choices_are_the_ones_the_scripts_know(self):
        self.assertEqual(tuple(node("Object.keys(plan.PLATFORMS)")), PLATFORMS)
        systems = node("plan.SYSTEMS")
        self.assertEqual(tuple(systems), SYSTEMS)
        first_boot = (ROOT / "controller" / "first-boot.sh").read_text()
        for name, system in systems.items():
            self.assertTrue((ROOT / "controller" / system["installer"]).is_file(), name)
            # first-boot.sh picks the same installer for the same /etc/os-release ID.
            self.assertRegex(first_boot, rf"(?m)^\s+(?:\w+\|)*{name}(?:\|\w+)*\) installer={re.escape(system['installer'])} ;;")

    def test_a_new_vm_installs_at_first_boot_except_rhel_outside_azure(self):
        for case, method, _steps in self.each():
            expected = "commands" if case["platform"] == "existing" or (
                case["system"] == "rhel" and case["platform"] != "azure") else "first-boot"
            self.assertEqual(method, expected, case)
        reason = node("plan.method(args[0]).reason", answers("proxmox", "rhel"))
        self.assertIn("registered", reason)
        self.assertEqual(node("plan.method(args[0]).reason", answers("existing", "rhel")), "")

    def test_the_filled_file_differs_from_the_guides_in_the_four_values_only(self):
        for case, method, steps in self.each():
            if method != "first-boot":
                self.assertFalse(any("file" in step for step in steps), case)
                continue
            [filled] = [step["file"] for step in steps if "file" in step]
            self.assertEqual(filled["name"], "controller-first-boot.yaml")
            changed = [(old, new) for old, new in zip(USER_DATA.splitlines(), filled["content"].splitlines()) if old != new]
            expected = [("      admin=REPLACE_WITH_ADMIN_LOGIN", f"      admin={case['admin']}")]
            if case["expose"] == "https":
                expected.append(("      expose=tunnel", "      expose=https"))
            if case["address"]:
                expected.append(("      address=", f"      address={case['address']}"))
            self.assertEqual(changed, expected, case)
            self.assertEqual(len(filled["content"].splitlines()), len(USER_DATA.splitlines()))
            [conf] = yaml.safe_load(filled["content"])["write_files"]
            self.assertEqual(conf["content"].splitlines()[1], f"admin={case['admin']}")

    def test_another_release_reaches_the_file_the_commands_and_the_links(self):
        steps = node("plan.steps(args[0])", answers("azure", release="v1.14.0"))
        self.assertIn("\n      release=v1.14.0\n", steps[0]["file"]["content"])
        steps = node("plan.steps(args[0])", answers("existing", release="v1.14.0"))
        self.assertIn("git clone --branch v1.14.0 ", steps[1]["commands"][0]["code"])
        for link in (link for step in steps for link in step["links"]):
            self.assertIn("/blob/v1.14.0/docs/", link["href"])

    def test_every_step_has_a_title_a_place_and_something_to_see(self):
        for case, _method, steps in self.each():
            self.assertEqual(len({step["id"] for step in steps}), len(steps), case)
            self.assertEqual([step["id"] for step in steps[-3:]], ["open", "password", "machine"], case)
            for step in steps:
                for field in ("title", "where", "expect"):
                    self.assertTrue(step[field].strip(), (case, step["id"], field))
                self.assertTrue(step["text"], (case, step["id"]))
                self.assertNotIn("@@", json.dumps(step), "a placeholder of the page's source was left in")

    def test_commands_name_only_scripts_and_options_that_exist(self):
        usage = {name: (ROOT / "controller" / name).read_text() for name in ("install-controller.sh", "install-controller-el9.sh")}
        common = (ROOT / "controller" / "controller-common.sh").read_text()
        for case, _method, steps in self.each():
            code = "\n".join(command["code"] for step in steps for command in step["commands"])
            for script in re.findall(r"\bcontroller/[\w.-]+", code):
                self.assertTrue((ROOT / script).is_file(), (case, script))
            for line in code.splitlines():
                if "controller/install-controller" in line:
                    [installer] = re.findall(r"controller/(install-controller[\w-]*\.sh)", line)
                    self.assertEqual(installer, "install-controller.sh" if case["system"] == "ubuntu" else "install-controller-el9.sh")
                    for option in re.findall(r"(?<!\S)--[a-z-]+", line):
                        self.assertIn(f"{option})", common, (case, option))
                        self.assertIn(option, usage[installer], (case, option))

    def test_the_commands_for_a_vm_that_exists_are_stage_1s(self):
        stage_1 = (ROOT / "docs" / "stage-1-controller.md").read_text()
        for system in SYSTEMS:
            for expose, address in EXPOSURES:
                steps = {step["id"]: step for step in node("plan.steps(args[0])", answers("existing", system, expose, address))}
                self.assertEqual(list(steps), ["login", "guide", "plan", "install", "check", "open", "password", "machine"])
                *git, clone, enter = steps["guide"]["commands"][0]["code"].splitlines()
                for line in git + [enter]:
                    self.assertIn(f"\n{line}\n", stage_1, line)
                self.assertEqual(clone, "git clone --branch v1.13.0 https://github.com/kevo099/ansible-semaphore-guide.git "
                                        "~/ansible-semaphore-guide")
                installer = "install-controller.sh" if system == "ubuntu" else "install-controller-el9.sh"
                self.assertEqual(steps["plan"]["commands"][0]["code"], f"sudo bash controller/{installer}")
                options = {"tunnel": "", "https": " --expose https"}[expose] + (f" --address {address}" if address else "")
                self.assertEqual(steps["install"]["commands"][0]["code"], f"sudo bash controller/{installer} --apply{options}")
                self.assertEqual(steps["check"]["commands"][0]["code"], "sudo python3.12 controller/check-controller.py")
                self.assertIn("\nsudo python3.12 controller/check-controller.py\n", stage_1)

    def test_the_tunnel_the_password_and_the_first_machine_are_the_guides_commands(self):
        stage_1 = (ROOT / "docs" / "stage-1-controller.md").read_text()
        stage_2 = (ROOT / "docs" / "stage-2-existing-machines.md").read_text()
        stage_4 = (ROOT / "docs" / "stage-4-add-target-first-job.md").read_text()
        steps = {step["id"]: step for step in node("plan.steps(args[0])", answers("azure"))}
        tunnel = steps["open"]["commands"][0]["code"]
        self.assertIn(tunnel.replace("ada@", "ADMIN@"), stage_1)
        self.assertIn("http://127.0.0.1:8088/", steps["open"]["text"][0])
        self.assertEqual(steps["password"]["commands"][0]["code"], "sudo cat /etc/semaphore/initial-admin-password")
        enter, onboard, sudo = steps["machine"]["commands"][0]["code"].splitlines()
        self.assertIn(f"\n{enter}\n{onboard.replace('MACHINE_ADDRESS', 'VM_ADDRESS')}\n", stage_2)
        self.assertIn(f"\n{sudo}\n", stage_4)
        https = {step["id"]: step for step in node("plan.steps(args[0])", answers("azure", expose="https"))}
        self.assertIn("ansible-guide-first-boot.log", https["open"]["commands"][0]["code"])
        existing = {step["id"]: step for step in node("plan.steps(args[0])", answers("existing", expose="https"))}
        self.assertIn("\nsudo bash controller/expose-semaphore.sh --mode https\n", stage_1)
        self.assertEqual(existing["open"]["commands"][0]["code"], "sudo bash controller/expose-semaphore.sh --mode https")

    def test_the_first_boot_steps_read_the_log_the_script_writes(self):
        script = (ROOT / "controller" / "first-boot.sh").read_text()
        steps = {step["id"]: step for step in node("plan.steps(args[0])", answers("proxmox"))}
        self.assertEqual(steps["wait"]["commands"][0]["code"],
                         "cloud-init status --wait\nsudo tail -n 4 /var/log/ansible-guide-first-boot.log")
        self.assertIn("log=/var/log/ansible-guide-first-boot.log\n", script)
        for line in ("first-boot: RESULT: OK", "RESULT: STOPPED:"):
            self.assertIn(line, steps["wait"]["expect"])
            self.assertIn(line.removeprefix("first-boot: "), script)

    def test_the_proxmox_commands_are_stage_3s_with_the_controllers_size(self):
        stage_3 = (ROOT / "docs" / "stage-3-new-vms-cloud-init.md").read_text()
        page = (ROOT / "docs" / "first-boot-controller.md").read_text()
        for system in ("ubuntu", "almalinux", "rocky"):
            [create] = [step for step in node("plan.steps(args[0])", answers("proxmox", system)) if step["id"] == "create"]
            copy, on_node = create["commands"]
            file_copy, key_copy = copy["code"].splitlines()
            self.assertEqual(file_copy, "scp controller-first-boot.yaml root@PROXMOX_NODE:/var/lib/vz/snippets/"
                                        "controller-first-boot.yaml")
            # Stage 3's own example of getting the key onto the node, and its two prerequisites.
            self.assertIn(f"`{key_copy}`", stage_3)
            self.assertIn(f"{file_copy}\n{key_copy}\n", page)
            self.assertEqual([link["href"].rsplit("#", 1)[1] for link in create["links"]][:2],
                             ["do-enable-snippets-on-a-storage", "do-build-a-vm-from-a-cloud-image"])
            self.assertIn("--ciupgrade 0", create["note"])
            lines = on_node["code"].replace("--ciuser ada ", "--ciuser ADMIN ").splitlines()
            same = [line for line in lines if not re.search(r"--memory|qm resize|--cicustom|qm start", line)]
            for line in same:
                self.assertIn(f"   {line}\n", stage_3, line)
            self.assertEqual("qm set VMID --rng0 source=/dev/urandom" in lines, system != "ubuntu")
            self.assertEqual(lines[-2:], ['qm set VMID --cicustom "vendor=local:snippets/controller-first-boot.yaml"',
                                          "qm start VMID"])
            # The size is the controller's from Stage 0, and the guide's own page shows the same commands.
            self.assertIn("--cores 2 --memory 4096 \\", lines[0])
            self.assertIn("qm resize VMID scsi0 32G", lines)
            for line in lines:
                if "--rng0" not in line:
                    self.assertIn(f"{line}\n", page, line)
        self.assertIn("| Controller | `controller.example.test` | Ubuntu 24.04, or RHEL, AlmaLinux or Rocky Linux 9.4 or "
                      "later | 2 | 4 GiB | 32 GiB |", (ROOT / "docs" / "stage-0-plan.md").read_text())

    def test_the_seed_commands_are_stage_3s_with_this_file(self):
        stage_3 = (ROOT / "docs" / "stage-3-new-vms-cloud-init.md").read_text()
        for system, user in (("ubuntu", "ubuntu"), ("almalinux", "almalinux"), ("rocky", "rocky")):
            [create] = [step for step in node("plan.steps(args[0])", answers("seed", system, admin=user)) if step["id"] == "create"]
            code = create["commands"][0]["code"]
            self.assertIn("cp ~/controller-first-boot.yaml vendor-data\n", code)
            self.assertIn(f"the image's own user, {user}.", create["note"])
            for line in code.replace("seed-controller", "seed-NAME").replace("controller-1 controller", "NAME-1 NAME").splitlines():
                if not line.startswith(("cp ", "hostname:", "fqdn:")):
                    self.assertIn(f"{line}\n", stage_3, line)
            self.assertIn(f"`{user}`", stage_3)
            # Another login would give a file whose first boot must stop, so the page asks for the right one.
            self.assertEqual(node("plan.validate(args[0])", answers("seed", system)),
                             {"admin": f"With a seed ISO the administrator is the image's own user, which on "
                                       f"{node('plan.SYSTEMS[args[0]].label', system)} is {user}. Enter {user}."})
        # RHEL there installs by commands on a VM that exists, with whatever administrator it has.
        self.assertEqual(node("plan.validate(args[0])", answers("seed", "rhel")), {})
        self.assertEqual({name: system["defaultUser"] for name, system in node("plan.SYSTEMS").items()}, IMAGE_USER)

    def test_azure_names_the_field_the_guide_names(self):
        azure = (ROOT / "docs" / "platform-azure.md").read_text()
        for system in SYSTEMS:
            [create] = [step for step in node("plan.steps(args[0])", answers("azure", system, "https")) if step["id"] == "create"]
            text = " ".join(create["list"])
            for words in ("Advanced tab, Custom data", "SSH public key", "username ada", "SSH (22) and HTTPS (443)",
                          "only from your own address", "2 vCPUs, 4 GiB"):
                self.assertIn(words, text)
            self.assertIn("--custom-data", create["note"])
            self.assertEqual("pay-as-you-go RHEL image" in create["note"], system == "rhel")
        self.assertIn("**Advanced → Custom data**", azure)
        self.assertIn("pay-as-you-go RHEL image already has working repositories", azure)

    def test_every_link_goes_to_a_page_and_a_heading_of_the_guide(self):
        prefix = node("plan.REPOSITORY") + "/blob/v1.13.0/"
        seen = set()
        for _case, _method, steps in self.each():
            for link in (link for step in steps for link in step["links"]):
                self.assertTrue(link["text"].strip())
                self.assertTrue(link["href"].startswith(prefix + "docs/"), link["href"])
                seen.add(link["href"])
        self.assertGreater(len(seen), 10)
        for href in sorted(seen):
            parsed = urlsplit(href)
            page = ROOT / parsed.path.split("/blob/v1.13.0/", 1)[1]
            self.assertTrue(page.is_file(), href)
            if parsed.fragment:
                self.assertIn(parsed.fragment, validator.headings(page.read_text()), href)

    def test_values_that_could_change_a_command_are_refused(self):
        for value in HOSTILE + ("", "root", "semaphore", "svc_ansible"):
            with self.subTest(admin=value):
                self.assertIn("admin", node("plan.validate(args[0])", answers(admin=value)))
        for value in ("https://controller.example.test", "controller.example.test/path", "a b", "-x", "$(id)", "a;b"):
            with self.subTest(address=value):
                self.assertIn("address", node("plan.validate(args[0])", answers(expose="https", address=value)))
        # A release is a tag of the guide and nothing else: a path could send every link to another repository.
        for value in ("v1.13.0 --upload-pack=x", "--upload-pack=x", "v1;id", "$(id)", "main", "feat/x", "v1.13",
                      "v1.13.0/../../../../other/fork/blob/main", "v1.13.0/"):
            with self.subTest(release=value):
                self.assertIn("release", node("plan.validate(args[0])", answers(release=value)))
        self.assertEqual(node("plan.validate(args[0])", answers("azure", "rhel", "https", "controller.example.test")), {})
        refused = node("(() => { try { plan.steps(args[0]); return 'steps'; } catch (e) { try { plan.userData(args[0]); "
                       "return 'file'; } catch (f) { return 'refused'; } } })()", answers(admin="ada; id"))
        self.assertEqual(refused, "refused")

    def test_the_page_lets_through_only_what_the_scripts_take(self):
        source = (SITE / "plan.js").read_text()
        script = (ROOT / "controller" / "first-boot.sh").read_text()
        bootstrap = yaml.safe_load(USER_DATA)["runcmd"][0][2]
        # The login: one pattern, in JavaScript with a length and in Bash without.
        self.assertIn("var ADMIN = /^[A-Za-z_][A-Za-z0-9_.-]{0,31}$/;", source)
        for text in (script, bootstrap):
            self.assertIn("[[ $admin != REPLACE_WITH_ADMIN_LOGIN && $admin =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]]", text)
        # The release: the page takes tags only, which the command in the file takes too.
        self.assertIn(r"var RELEASE_NAME = /^v[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$/;", source)
        self.assertIn("[[ $release =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]]", bootstrap)
        # The address: whatever the page lets through, expose-semaphore.sh's own rule takes, here in Python.
        def script_takes(address):
            if re.fullmatch(r"[0-9.]+", address) or ":" in address:
                try:
                    ipaddress.ip_address(address)
                except ValueError:
                    return False
                return "%" not in address
            return bool(re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?", address))
        samples = [IPV4, IPV4 + ":443", "192.0.2.300", "1.2.3", "01.2.3.4", "controller.example.test",
                   "controller.example.test.", "controller.example.test:8443", "-controller", "controller-", "c", "a..b",
                   IPV6, f"[{IPV6}]", IPV6 + "%eth0", "https://controller.example.test", "a b", "a" * 253, "a" * 254]
        verdicts = node("args[0].map((address) => !('address' in plan.validate({admin: 'ada', expose: 'https', address})))",
                        samples)
        for address, page_takes in zip(samples, verdicts):
            with self.subTest(address=address):
                self.assertLessEqual(page_takes, script_takes(address))
        taken = [address for address, page_takes in zip(samples, verdicts) if page_takes]
        # IPv6 is the one thing the script takes and the page leaves to the command line.
        self.assertEqual(taken, [IPV4, "controller.example.test", "c", "a..b", "a" * 253])

    def test_an_address_without_https_is_dropped_not_passed_on(self):
        steps = node("plan.steps(args[0])", answers("azure", expose="tunnel", address="controller.example.test"))
        self.assertIn("\n      address=\n", steps[0]["file"]["content"])

    def test_the_answers_survive_the_address_bar(self):
        case = answers("azure", "rocky", "https", "controller.example.test")
        encoded = node("plan.encode(args[0])", case)
        self.assertEqual(encoded, "platform=azure&system=rocky&admin=ada&expose=https&address=controller.example.test")
        decoded = node("plan.decode(args[0])", "#" + encoded + "&view=steps&other=1")
        self.assertEqual(decoded, dict(case, release="v1.13.0"))
        # A name without a value is no value: "#admin" must not make an administrator called admin.
        self.assertEqual(node("plan.decode(args[0])", "#admin&system&view=steps")["admin"], "")
        # Unknown choices fall back to the defaults, and a broken escape is ignored.
        self.assertEqual(node("plan.decode(args[0])", "#platform=nowhere&system=plan9&expose=ftp&admin=%E0%A4%A"),
                         dict(platform="proxmox", system="ubuntu", admin="", expose="tunnel", address="", release="v1.13.0"))


class PageSourceTests(unittest.TestCase):
    """The page as files: what a web server would hand out."""

    def test_the_folder_holds_the_four_files_of_the_page_and_its_readme(self):
        self.assertEqual(sorted(path.name for path in SITE.iterdir()),
                         ["README.md", "index.html", "plan.js", "setup.css", "setup.js"])

    def test_the_page_loads_nothing_from_another_site(self):
        html = (SITE / "index.html").read_text()
        self.assertEqual(re.findall(r'(?:src|href)="([^"#]+)"', html.replace('href="data:', 'x="')),
                         ["setup.css", "plan.js", "setup.js"])
        # No policy in the page itself: from a clone, some browsers match 'self' to no file at all.
        # A server sends it as a header, which site/README.md gives; nothing inline would break under it.
        self.assertNotIn("Content-Security-Policy", html)
        self.assertIn("`Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src data:; "
                      "base-uri 'none'; form-action 'none'`", (SITE / "README.md").read_text())
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")
        self.assertNotRegex(html, r"\sstyle=|\son[a-z]+=")
        for name in ("setup.css", "setup.js"):
            self.assertNotRegex((SITE / name).read_text(), r"https?://|@import|url\(")
        urls = {url.rstrip(".,") for url in re.findall(r"https?://[^\s'\"`)]+", (SITE / "plan.js").read_text())}
        # The last one is the word in "without https://", which the page says about an address.
        self.assertEqual(urls, {"https://github.com/kevo099/ansible-semaphore-guide", "http://127.0.0.1:8088/",
                                "https://github.com/kevo099/ansible-semaphore-guide.git", "https://"})

    def test_the_page_writes_answers_as_text_never_as_markup(self):
        script = (SITE / "setup.js").read_text()
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(forbidden, script)
        self.assertNotIn("localStorage", script)
        self.assertNotRegex(script, r"\bfetch\(|XMLHttpRequest|WebSocket|sendBeacon")

    def test_every_field_the_script_reads_is_on_the_page(self):
        html = (SITE / "index.html").read_text()
        script = (SITE / "setup.js").read_text()
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        for wanted in set(re.findall(r"byId\('([\w-]+)'\)", script)):
            self.assertIn(wanted, ids)
        for field in ("admin", "address", "release"):
            self.assertIn(f"{field}-error", ids)
            self.assertIn(f'<label for="{field}">', html)

    def test_the_readme_lists_the_files_and_the_platforms(self):
        readme = (SITE / "README.md").read_text()
        for name in ("index.html", "setup.css", "plan.js", "setup.js", "Proxmox VE", "Microsoft Azure", "Another hypervisor",
                     "A VM that already exists"):
            self.assertIn(name, readme)


if __name__ == "__main__":
    unittest.main()
