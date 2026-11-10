#!/usr/bin/env python3
"""Create the initial admin from a root-only file without logging its password."""

import subprocess
from pathlib import Path


def main():
    marker = Path("/etc/semaphore/.initial-admin-created")
    if marker.exists():
        raise SystemExit("Initial admin already created; use the documented account recovery procedure")
    password = Path("/etc/semaphore/initial-admin-password").read_text().strip()
    if len(password) < 32:
        raise SystemExit("Initial password file is invalid")
    # This pinned CLI only accepts --password. The value is not in shell history
    # or our output, but it briefly exists in the child process's argument list.
    result = subprocess.run(
        [
            "runuser", "-u", "semaphore", "--", "/usr/local/bin/semaphore",
            "user", "add", "--admin", "--login", "admin", "--name", "Lab Administrator",
            "--email", "admin@example.test", "--password", password,
            "--config", "/etc/semaphore/config.json",
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        # Do not echo the argv, password or arbitrary subprocess output on error.
        raise SystemExit("Admin creation failed; inspect the local database and account state")
    marker.touch(mode=0o600, exist_ok=False)
    print("Created the initial admin. Retrieve the password privately on the controller.")


if __name__ == "__main__":
    main()
