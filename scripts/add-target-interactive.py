#!/usr/bin/env python3
"""Add one prepared target to a seeded controller's local inventory over verified SSH."""

import argparse
from contextlib import ExitStack
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time


PROBE = '''import json, shlex, socket
from pathlib import Path
release = {}
for line in Path('/etc/os-release').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key, value = line.split('=', 1)
        words = shlex.split(value)
        release[key] = words[0] if words else ''
print(json.dumps({'hostname': socket.gethostname().split('.', 1)[0],
                  'id': release.get('ID', ''), 'version': release.get('VERSION_ID', '')}))
'''


class Stop(Exception):
    """An expected failure with an actionable message."""


def require(condition, message):
    if not condition:
        raise Stop(message)


def run(args, data=None, timeout=25):
    try:
        return subprocess.run(args, input=data, text=True, capture_output=True,
                              timeout=timeout, env=dict(os.environ, LC_ALL='C'))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop(f"Could not run {args[0]}: {exc}") from exc


def ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise Stop('Enter one IPv4 address, without a port, prefix or hostname.') from exc
    require(not (address.is_loopback or address.is_link_local or address.is_multicast
                 or address.is_unspecified or int(address) == (1 << 32) - 1),
            'Enter a unicast target IPv4 address reachable from this controller.')
    return str(address)


def hostname(value):
    require(isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,62}', value)),
            'Inventory name must be a plain hostname, at most 63 characters.')
    return value


def group_for(info):
    distro, version = info['id'], info['version']
    require(isinstance(distro, str) and isinstance(version, str), 'Invalid OS information from target.')
    if distro == 'ubuntu' and version == '24.04':
        return 'ubuntu'
    if distro in ('rhel', 'almalinux', 'rocky') and re.fullmatch(r'9(?:\.[0-9]+)*', version):
        return 'enterprise_linux'
    raise Stop('Supported targets: Ubuntu 24.04 or RHEL/AlmaLinux/Rocky Linux 9.')


def fingerprint(line):
    result = run(['ssh-keygen', '-l', '-E', 'sha256', '-f', '-'], line + '\n')
    require(result.returncode == 0 and len(result.stdout.split()) >= 2, 'Could not fingerprint an SSH key.')
    return result.stdout.split()[1]


def verified_key(address, trust):
    print(f'Checking SSH on {address}:22 ...')
    scan = run(['ssh-keyscan', '-T', '5', '-t', 'rsa', '--', address])
    keys = set()
    for line in scan.stdout.splitlines():
        words = line.split()
        if len(words) == 3 and words[0] == address and words[1] == 'ssh-rsa':
            keys.add(' '.join(words))
    require(len(keys) == 1, 'No unique RSA host key received. Check the IP, route, SSH service and port 22 firewall.')
    key = keys.pop()
    scanned = fingerprint(key)
    lookup = run(['ssh-keygen', '-F', address, '-f', str(trust)])
    require(lookup.returncode in (0, 1), 'Could not read existing SSH trust.')
    existing = [line for line in lookup.stdout.splitlines() if line and not line.startswith('#')]
    trusted = False
    for line in existing:
        words = line.split()
        require(len(words) >= 3 and not words[0].startswith('@'),
                'Existing host trust has a marker or invalid entry; review it manually.')
        if words[1] == 'ssh-rsa':
            require(fingerprint(line) == scanned,
                    'The RSA host key differs from existing trust. Verify any rebuild; no files were changed.')
            trusted = True
    if trusted:
        print('RSA host key matches the controller\'s existing trusted entry.')
    else:
        print('First connection: read the RSA fingerprint through the target console or Azure Run Command:')
        print('  ssh-keygen -l -E sha256 -f /etc/ssh/ssh_host_rsa_key.pub')
        wanted = input('Paste that SHA256:... fingerprint here: ').strip()
        require(bool(re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', wanted)), 'Paste only the complete SHA256:... fingerprint.')
        require(wanted == scanned, 'Fingerprint mismatch. Check the target identity; no files were changed.')
        print('RSA host key verified.')
    return key, trusted


def inspect_target(address, key, private_key):
    # Pin the verified key in an isolated file while probing. Permanent trust is
    # updated only after both SSH authentication and the inventory checks pass.
    with tempfile.TemporaryDirectory(prefix='ansible-target-') as folder:
        pinned = Path(folder) / 'known_hosts'
        pinned.write_text(key + '\n')
        args = ['ssh', '-F', '/dev/null', '-i', str(private_key),
                '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
                '-o', 'BatchMode=yes', '-o', 'PasswordAuthentication=no',
                '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={pinned}',
                '-o', 'GlobalKnownHostsFile=/dev/null',
                '-o', 'HostKeyAlgorithms=rsa-sha2-512,rsa-sha2-256',
                '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
                '-o', 'RequestTTY=no', '-o', 'ClearAllForwardings=yes',
                '-l', 'svc_ansible', address, 'python3 -']
        result = run(args, PROBE)
    require(result.returncode == 0,
            'SSH probe failed. Check svc_ansible has this controller\'s public key, the account is usable, '
            'SSH permits RSA SHA-2, and python3 is installed. No files were changed.\n'
            + 'SSH diagnostic: ' + ascii(result.stderr.strip()[-1500:]))
    try:
        info = json.loads(result.stdout)
        group = group_for(info)
        name = hostname(info['hostname'])
    except (ValueError, KeyError, TypeError) as exc:
        raise Stop('The target did not return valid hostname/OS information; no files were changed.') from exc
    return name, group


def inventory_update(content, name, address, group):
    lines = content.splitlines()
    section, headers, entries, children = '', [], [], []
    for index, line in enumerate(lines):
        words = shlex.split(line, comments=True)
        if not words:
            continue
        clean = ' '.join(words)
        header = re.fullmatch(r'\[([^]]+)\]', clean)
        if header:
            section = header[1]
            if section == group:
                headers.append(index)
            continue
        if section == 'lab:children':
            children.append(clean)
        if ':' in section:
            continue
        destinations = [token.split('=', 1)[1] for token in words[1:] if token.startswith('ansible_host=')]
        if words[0] == name:
            entries.append((section, words))
        elif words[0] == address or address in destinations:
            raise Stop('This IP already has another inventory name; review that entry first.')
    require(len(headers) == 1 and group in children,
            f'Inventory must contain one [{group}] section and include it in [lab:children].')
    expected = [name, 'ansible_host=' + address]
    require(not entries or entries == [(group, expected)],
            'This inventory name already has different settings; review that entry first.')
    if entries:
        return content
    lines.insert(headers[0] + 1, ' '.join(expected))
    return '\n'.join(lines) + '\n'


def lock_file(stack, path):
    # Keep the original inodes (and their service ownership/modes) when writing.
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    handle = stack.enter_context(os.fdopen(fd, 'r+', encoding='utf-8', newline=''))
    require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), f'Expected a regular file: {path}')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise Stop(f'Another helper is editing {path}; try again after it finishes.') from exc
    return handle


def write_handle(handle, content):
    handle.seek(0)
    handle.write(content)
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


def save_changes(handles, original, updated):
    changes = {path: text for path, text in updated.items() if text != original[path]}
    # Locks coordinate this helper; compare contents/inodes to catch other editors
    # that changed either file while the operator was answering prompts.
    for path, handle in handles.items():
        handle.seek(0)
        require(not path.is_symlink() and os.path.samestat(path.stat(), os.fstat(handle.fileno()))
                and handle.read() == original[path],
                f'{path} changed during this session; run the helper again.')
    stamp = '.before-add-' + str(time.time_ns())
    for path in changes:
        shutil.copy2(path, str(path) + stamp)
    try:
        for path, content in changes.items():
            write_handle(handles[path], content)
    except BaseException:
        # Also restore an interrupted write. A power loss/SIGKILL still needs the backups.
        for path in changes:
            write_handle(handles[path], original[path])
        raise
    for path in changes:
        print(f'Backup: {path}{stamp}')
    return bool(changes)


def add_target(args):
    inventory = args.lab_dir / 'inventories/lab.ini'
    trust, private_key = args.known_hosts, args.key
    require(inventory.resolve() != trust.resolve(), 'Inventory and known-hosts must be separate files.')
    require(private_key.is_file() and not private_key.is_symlink(), f'Missing regular service SSH key: {private_key}')
    require(stat.S_IMODE(private_key.stat().st_mode) & 0o077 == 0,
            f'Service SSH key permissions must exclude group/other access: {private_key}')
    print('Add a prepared target to the controller inventory')
    print(f'Inventory: {inventory}\nSSH identity: svc_ansible, key {private_key}')
    print('The target must already be onboarded with this controller\'s public key.')
    with ExitStack() as stack:
        handles = {path: lock_file(stack, path) for path in (inventory, trust)}
        original = {path: handle.read() for path, handle in handles.items()}
        address = ipv4(input('Target IPv4 address: ').strip())
        key, already_trusted = verified_key(address, trust)
        name, group = inspect_target(address, key, private_key)
        print(f'SSH login succeeded. Detected {name} in group [{group}].')
        name = hostname(input(f'Inventory name [{name}]: ').strip() or name)
        updated = {inventory: inventory_update(original[inventory], name, address, group),
                   trust: original[trust]}
        if not already_trusted:
            updated[trust] = original[trust].rstrip('\n') + '\n' + key + '\n'
        if updated == original:
            print(f'Already present: {name}. SSH verified; no changes needed.')
            return
        print(f'Entry: [{group}] {name} ansible_host={address}')
        if input('Save this target to inventory and SSH trust? [y/N]: ').strip().lower() not in ('y', 'yes'):
            print('Cancelled; no files changed.')
            return
        save_changes(handles, original, updated)
    print(f'Added {name}. Inventory: {inventory}')
    print(f'Next: in Semaphore use the local-file inventory and run Ping with Limit = {name}.')
    print('Sudo/password access was not tested; select the sudo credential and run Baseline preview next.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab-dir', type=Path, default=Path('/opt/ansible-lab'))
    parser.add_argument('--known-hosts', type=Path, default=Path('/etc/semaphore/known_hosts'))
    parser.add_argument('--key', type=Path, default=Path('/etc/semaphore/svc_ansible'))
    args = parser.parse_args(argv)
    try:
        require(os.geteuid() == 0, 'Run with sudo python3: the controller service files are root-owned.')
        for tool in ('ssh', 'ssh-keyscan', 'ssh-keygen'):
            require(shutil.which(tool), f'Missing controller command: {tool}')
        os.umask(0o077)
        add_target(args)
    except (Stop, OSError, ValueError) as exc:
        print(f'STOP: {exc}', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled. If writing had begun, inspect the before-add backups.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
