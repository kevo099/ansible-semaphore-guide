#!/usr/bin/env python3
"""Generate a private controller configuration locally; never print its values."""

import argparse
import base64
import json
import os
from pathlib import Path
import secrets


def make_config():
    def random_key():
        return base64.b64encode(secrets.token_bytes(32)).decode("ascii")

    return {
        "postgres": {
            "host": "127.0.0.1:5432",
            "user": "semaphore",
            "pass": secrets.token_hex(24),
            "name": "semaphore",
            "options": {"sslmode": "disable"},
        },
        "dialect": "postgres",
        "interface": "127.0.0.1",
        "port": ":3000",
        "tmp_path": "/var/lib/semaphore/tmp",
        "home_dir_mode": "user_home",
        "cookie_hash": random_key(),
        "cookie_encryption": random_key(),
        "access_key_encryption": random_key(),
        "max_parallel_tasks": 1,
        "git_client": "cmd_git",
        "env_vars": {
            "PATH": "/opt/ansible-venv/bin:/usr/local/bin:/usr/bin:/bin",
            "GIT_CONFIG_GLOBAL": "/etc/semaphore/gitconfig",
            "ANSIBLE_HOST_KEY_CHECKING": "True",
            "ANSIBLE_SSH_ARGS": (
                "-o UserKnownHostsFile=/etc/semaphore/known_hosts "
                "-o StrictHostKeyChecking=yes"
            ),
        },
    }


def write_new(path, content, mode=0o600):
    """O_EXCL also refuses symlinks and existing files; failure preserves them."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error("Create the private destination directory first")
    config_path = args.directory / "config.json"
    admin_path = args.directory / "initial-admin-password"
    if config_path.exists() or admin_path.exists():
        parser.error("Existing configuration or admin password; refusing to replace it")
    write_new(config_path, json.dumps(make_config(), indent=2) + "\n")
    write_new(admin_path, secrets.token_urlsafe(32) + "\n")
    print("Created private configuration files. No credential values were printed.")


if __name__ == "__main__":
    main()
