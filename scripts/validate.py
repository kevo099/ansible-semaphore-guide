#!/usr/bin/env python3
"""Check public source and examples offline; never run installation or jobs."""

import ast
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", ".cache", ".ansible", "__pycache__"}
errors = []
counts = {"files": 0, "local_links": 0, "shell_blocks": 0, "data_blocks": 0, "cloud_init_scripts": 0}


def fail(path, reason):
    # Print the location and rule, never the matched value.
    errors.append(f"{path.relative_to(ROOT)}: {reason}")


def source_files(root=ROOT):
    # A clone has a .git directory; a linked worktree has a .git file. Both honor .gitignore.
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root, check=True, capture_output=True, text=True,
        )
        return [root / name for name in sorted(set(result.stdout.split("\0")) - {""})]
    return sorted(p for p in root.rglob("*") if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS))


def headings(text):
    # A '#' line inside a fenced example is a comment, not a heading GitHub can link to.
    text = re.sub(r"^```.*?^```", "", text, flags=re.MULTILINE | re.DOTALL)
    anchors = set()
    seen = {}
    for title in re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug + (f"-{count}" if count else ""))
    return anchors


def shell_syntax(path, content):
    result = subprocess.run(["bash", "-n"], input=content, text=True, capture_output=True)
    if result.returncode:
        fail(path, "invalid Bash syntax (inspect locally)")


def cloud_init_scripts(documents):
    # cloud-init hands a string command to the shell and runs a list as given, so a
    # [/bin/bash, -c, SCRIPT] entry carries a whole script.
    for document in documents:
        if not isinstance(document, dict):
            continue
        for command in (document.get("bootcmd") or []) + (document.get("runcmd") or []):
            if isinstance(command, str):
                yield command
            elif (isinstance(command, list) and len(command) >= 3 and Path(str(command[0])).name in {"bash", "sh"}
                    and command[1] == "-c" and isinstance(command[2], str)):
                yield command[2]


def publication_boundary(path, text):
    forbidden_names = {"config.json", "known_hosts", ".env", "initial-admin-password"}
    if path.name in forbidden_names or path.suffix in {".pem", ".key", ".dump", ".log", ".zip", ".gz"}:
        fail(path, "private/runtime file cannot be published")
    # Keep the patterns split so this validator does not match its own examples.
    patterns = {
        # Any PEM private key header: RSA, EC, OPENSSH, PKCS#8 and ENCRYPTED alike.
        "private key material": r"-----BEGIN [A-Z0-9 ]*PRIVATE" + r" KEY",
        "GitHub credential": r"\bgh[pousr]_" + r"[A-Za-z0-9]{30,}",
        "GitHub fine-grained credential": r"github_pat_" + r"[A-Za-z0-9_]{30,}",
        "cloud credential identifier": r"\b(?:AKIA|ASIA)" + r"[A-Z0-9]{16}\b",
        # Storage and Service Bus connection strings, SAS URLs and Entra application secrets.
        "Azure account key": r"(?:AccountKey|SharedAccessKey)=" + r"[A-Za-z0-9+/=]{20,}",
        "Azure shared access signature": r"SharedAccess" + r"Signature=\S{20,}|[?&]sig=" + r"[A-Za-z0-9%+/=]{10,}",
        "Microsoft Entra client secret": r"\b[A-Za-z0-9_~.]{3}\d" + r"Q~[A-Za-z0-9_~.-]{31,34}\b",
        # SMBIOS, Windows and Azure tools print the same identifiers in upper case.
        "machine/account identifier": r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        # Any account's home except the lab service account, with or without a trailing slash.
        # The service account's home may still end a sentence. macOS and Windows homes count
        # too, also JSON-escaped; an API path such as /scim/v2/Users/ID does not.
        "personal workspace path": (r"/home/" + r"(?!svc_ansible(?![\w-]|\.\w))[A-Za-z0-9_.-]+"
                                    r"|(?<![\w.-])/Users/" + r"[\w.-]+"
                                    r"|(?i:\b[A-Z]:\\{1,2}Users\\{1,2})" + r"[\w.-]+"),
        "credentials embedded in URL": r"https?://[^\s/:]+:[^\s/@]+@",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, text):
            fail(path, label)
    # E-mail addresses, such as the account `az account show` prints. Git's SSH remote, systemd
    # instance units, SSH algorithm names and reserved example domains only look like one.
    for local, domain in re.findall(r"(?<![\w.+-])([\w.+-]+)@([\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,})\b", text):
        domain = domain.lower()
        if (f"{local}@{domain}" == "git@github.com" or domain in {"openssh.com", "libssh.org"}
                or domain.rsplit(".", 1)[1] in {"service", "socket", "target", "timer",
                                                "test", "example", "invalid", "localhost"}
                or re.search(r"(?:^|\.)example\.(?:com|net|org)$", domain)):
            continue
        fail(path, "personal e-mail address")
        break
    # A sentence may end with an address; only a further dotted digit group makes it a version.
    ipv4 = r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w|\.\d)"
    # IPv6 likewise. "::" alone is the unspecified address of listen examples such as [::]:443.
    ipv6 = r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:]|\.\d)"
    for match in re.findall(ipv4, text) + re.findall(ipv6, text):
        try:
            address = ipaddress.ip_address(match)
        except ValueError:
            continue
        if not (address.is_loopback or match == "::"):
            fail(path, "literal non-loopback address; use documentation hostnames")
            break
    # Owner names are case-insensitive, and clone and raw-file URLs are links too.
    owner_repository = r"(?i)(?:github\.com[/:]|githubusercontent\.com/)" + r"kevo099/([\w.-]+)"
    for repository in re.findall(owner_repository, text):
        if repository.lower().rstrip(".").removesuffix(".git") != "ansible-semaphore-guide":
            fail(path, "unreviewed owner repository link")
            break


def markdown(path, content):
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith("//"):
            continue
        linked = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
        if not linked.is_relative_to(ROOT) or not linked.exists():
            fail(path, "missing or out-of-repository local link")
        elif parsed.fragment and linked.suffix == ".md" and unquote(parsed.fragment) not in headings(linked.read_text()):
            fail(path, "unknown local heading anchor")
        counts["local_links"] += 1
    if len(re.findall(r"^```", content, re.MULTILINE)) % 2:
        fail(path, "unclosed fenced example")
    for language, body in re.findall(r"^```(\w*)\n(.*?)^```", content, re.MULTILINE | re.DOTALL):
        if language in {"bash", "sh"}:
            shell_syntax(path, body)
            counts["shell_blocks"] += 1
        elif language in {"yaml", "yml", "json"}:
            try:
                json.loads(body) if language == "json" else list(yaml.safe_load_all(body))
            except (ValueError, yaml.YAMLError):
                fail(path, "invalid structured-data example")
            counts["data_blocks"] += 1


def main():
    for path in source_files():
        if path.is_symlink() or not path.is_file():
            fail(path, "source must be a regular file")
            continue
        try:
            content = path.read_text()
        except UnicodeError:
            fail(path, "binary content requires separate publication review")
            continue
        counts["files"] += 1
        publication_boundary(path, content)
        if path.suffix == ".py":
            try:
                ast.parse(content)
            except SyntaxError:
                fail(path, "invalid Python syntax")
        elif path.suffix == ".sh":
            shell_syntax(path, content)
        elif path.suffix in {".yaml", ".yml"}:
            try:
                documents = list(yaml.safe_load_all(content))
            except yaml.YAMLError:
                fail(path, "invalid YAML")
                continue
            # A VM runs these at first boot, where a syntax error leaves it half prepared.
            if content.startswith("#cloud-config"):
                for script in cloud_init_scripts(documents):
                    shell_syntax(path, script)
                    counts["cloud_init_scripts"] += 1
        elif path.suffix == ".md":
            markdown(path, content)
    print(json.dumps({"passed": not errors, "counts": counts, "errors": errors}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
