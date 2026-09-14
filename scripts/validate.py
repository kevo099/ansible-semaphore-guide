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
counts = {"files": 0, "local_links": 0, "shell_blocks": 0, "data_blocks": 0}


def fail(path, reason):
    # Print the location and rule, never the matched value.
    errors.append(f"{path.relative_to(ROOT)}: {reason}")


def source_files():
    if (ROOT / ".git").is_dir():
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        return [ROOT / name for name in sorted(set(result.stdout.split("\0")) - {""})]
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS))


def headings(text):
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


def publication_boundary(path, text):
    forbidden_names = {"config.json", "known_hosts", ".env", "initial-admin-password"}
    if path.name in forbidden_names or path.suffix in {".pem", ".key", ".dump", ".log", ".zip", ".gz"}:
        fail(path, "private/runtime file cannot be published")
    # Keep the patterns split so this validator does not match its own examples.
    patterns = {
        "private key material": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE" + r" KEY-----",
        "GitHub credential": r"\bgh[pousr]_" + r"[A-Za-z0-9]{30,}",
        "GitHub fine-grained credential": r"github_pat_" + r"[A-Za-z0-9_]{30,}",
        "cloud credential identifier": r"\b(?:AKIA|ASIA)" + r"[A-Z0-9]{16}\b",
        "machine/account identifier": r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "personal workspace path": r"/home/" + r"(?!svc_ansible/)[A-Za-z0-9_.-]+/",
        "credentials embedded in URL": r"https?://[^\s/:]+:[^\s/@]+@",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, text):
            fail(path, label)
    for match in re.findall(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", text):
        try:
            address = ipaddress.ip_address(match)
        except ValueError:
            continue
        if not address.is_loopback:
            fail(path, "literal non-loopback address; use documentation hostnames")
            break
    for url in re.findall(r"https://github\.com/[^\s)\]>'\"`]+", text):
        parts = urlsplit(url).path.strip("/").split("/")
        if parts[0] == "kevo099" and len(parts) > 1 and parts[1].removesuffix(".git") != "ansible-semaphore-guide":
            fail(path, "unreviewed owner repository link")


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
                list(yaml.safe_load_all(content))
            except yaml.YAMLError:
                fail(path, "invalid YAML")
        elif path.suffix == ".md":
            markdown(path, content)
    print(json.dumps({"passed": not errors, "counts": counts, "errors": errors}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
