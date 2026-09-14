#!/usr/bin/env python3
"""Create the fresh guide database using a local private configuration."""

import json
import re
import subprocess
from pathlib import Path


def psql(sql):
    return subprocess.run(
        ["runuser", "-u", "postgres", "--", "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
        capture_output=True,
    ).stdout.strip()


def main():
    config = json.loads(Path("/etc/semaphore/config.json").read_text())
    database = config["postgres"]
    if database["user"] != "semaphore" or database["name"] != "semaphore":
        raise SystemExit("This helper is only for the fresh guide database")
    password = database["pass"]
    if not re.fullmatch(r"[0-9a-f]{48}", password):
        raise SystemExit("Expected the locally generated hexadecimal database password")
    if psql("SELECT 1 FROM pg_roles WHERE rolname='semaphore';"):
        raise SystemExit("Role already exists; do not overwrite an existing installation")
    if psql("SELECT 1 FROM pg_database WHERE datname='semaphore';"):
        raise SystemExit("Database already exists; do not overwrite an existing installation")
    # The generated password goes to psql on stdin, not its command line.
    psql("CREATE ROLE semaphore LOGIN PASSWORD '" + password + "';")
    subprocess.run(
        ["runuser", "-u", "postgres", "--", "createdb", "-T", "template0", "-O", "semaphore", "semaphore"],
        check=True,
    )
    print("Created the Semaphore database and its dedicated login role.")


if __name__ == "__main__":
    main()
