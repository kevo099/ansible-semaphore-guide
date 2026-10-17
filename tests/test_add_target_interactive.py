"""Offline controller workflow tests: SSH is simulated; ssh-keygen is real."""

import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from test_inventory_info import FP1, PUB1, PUB2, TEST_NET


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/add-target-interactive.py'
SPEC = importlib.util.spec_from_file_location('interactive_target', SCRIPT)
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)
ADDRESS = TEST_NET + '.10'


class InteractiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='interactive-target-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inventory = self.root / 'inventories/lab.ini'
        self.inventory.parent.mkdir()
        self.inventory.write_text(
            f'[ubuntu]\nold-host ansible_host={TEST_NET}.9\n\n'
            '[enterprise_linux]\n\n[lab:children]\nubuntu\nenterprise_linux\n'
            '\n[lab:vars]\nansible_user=svc_ansible\nansible_python_interpreter=/usr/bin/python3\n')
        self.trust = self.root / 'known_hosts'
        self.trust.write_text(f'# Unrelated trust\n{TEST_NET}.9 {PUB2}\n')
        for path in (self.inventory, self.trust):
            path.chmod(0o640)
        self.key = self.root / 'service_key'
        self.key.write_text('fixture: SSH is mocked, this is not a private key\n')
        self.key.chmod(0o600)
        self.args = SimpleNamespace(lab_dir=self.root, known_hosts=self.trust, key=self.key,
                                    trust_on_first_use=False)
        self.scan = f'{ADDRESS} {PUB1}\n'
        self.info = {'hostname': 'new-host', 'id': 'ubuntu', 'version': '24.04'}
        self.ssh_status = 0
        self.ssh_calls = []
        self.original = {p: p.read_bytes() for p in (self.inventory, self.trust)}
        self.real_run = HELPER.run

    def run_command(self, args, data=None, timeout=25):
        if args[0] == 'ssh-keyscan':
            self.assertEqual(args[-1], ADDRESS)
            return SimpleNamespace(stdout=self.scan, stderr='', returncode=0)
        if args[0] == 'ssh':
            self.ssh_calls.append(args)
            for option in ('StrictHostKeyChecking=yes', 'BatchMode=yes', 'IdentitiesOnly=yes',
                           'IdentityAgent=none', 'GlobalKnownHostsFile=/dev/null',
                           'HostKeyAlgorithms=rsa-sha2-512,rsa-sha2-256'):
                self.assertIn(option, args)
            self.assertIn(str(self.key), args)
            self.assertEqual(args[1:3], ['-F', '/dev/null'])
            self.assertEqual(args[-3:], ['svc_ansible', ADDRESS, 'python3 -'])
            pinned = Path(next(a.split('=', 1)[1] for a in args if a.startswith('UserKnownHostsFile=')))
            self.assertEqual(pinned.read_text(), self.scan)
            self.assertEqual(self.trust.read_bytes(), self.original[self.trust])
            self.assertEqual(data, HELPER.PROBE)
            return SimpleNamespace(stdout=json.dumps(self.info), stderr='Permission denied' if self.ssh_status else '',
                                   returncode=self.ssh_status)
        return self.real_run(args, data, timeout)

    def execute(self, replies=None):
        output = io.StringIO()
        with mock.patch.object(HELPER, 'run', side_effect=self.run_command), \
                mock.patch('builtins.input', side_effect=replies or [ADDRESS, FP1, '', 'y']), \
                contextlib.redirect_stdout(output):
            HELPER.add_target(self.args)
        return output.getvalue()

    def unchanged(self):
        for path, content in self.original.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse(list(self.root.rglob('*.before-add-*')))

    def test_add_then_repeat_uses_existing_trust_preserves_modes_and_backups(self):
        owners = {p: (p.stat().st_uid, p.stat().st_gid) for p in self.original}
        output = self.execute()
        self.assertIn('Added new-host', output)
        self.assertIn(f'[ubuntu]\nnew-host ansible_host={ADDRESS}\n', self.inventory.read_text())
        self.assertIn('old-host ansible_host=', self.inventory.read_text())
        self.assertTrue(self.trust.read_text().endswith(self.scan))
        backups = list(self.root.rglob('*.before-add-*'))
        self.assertEqual(len(backups), 2)
        for path, content in self.original.items():
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), owners[path])
            backup = next(p for p in backups if p.name.startswith(path.name + '.before-add-'))
            self.assertEqual(backup.read_bytes(), content)
        self.original = {p: p.read_bytes() for p in self.original}
        self.assertIn('Already present', self.execute([ADDRESS, '']))
        self.assertEqual(len(list(self.root.rglob('*.before-add-*'))), 2)
        self.assertEqual(self.inventory.read_text().count('new-host '), 1)
        self.assertEqual(len(self.ssh_calls), 2)

    def test_first_use_mode_adds_without_a_fingerprint_prompt(self):
        self.args.trust_on_first_use = True
        output = self.execute([ADDRESS, '', 'y'])
        self.assertIn('trust on first use', output)
        self.assertIn(FP1, output)
        self.assertNotIn('Paste that', output)
        self.assertIn(f'new-host ansible_host={ADDRESS}', self.inventory.read_text())
        self.assertTrue(self.trust.read_text().endswith(self.scan))
        self.assertEqual(len(self.ssh_calls), 1)

    def test_first_use_mode_still_refuses_existing_changed_keys(self):
        self.args.trust_on_first_use = True
        self.trust.write_text(self.trust.read_text() + f'{ADDRESS} {PUB2}\n')
        self.original[self.trust] = self.trust.read_bytes()
        with self.assertRaisesRegex(HELPER.Stop, 'differs from existing trust'):
            self.execute([ADDRESS])
        self.assertFalse(self.ssh_calls)
        self.unchanged()

    def test_first_use_mode_does_not_bypass_existing_other_key_type(self):
        self.args.trust_on_first_use = True
        blob = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes([1]) * 32
        public = 'ssh-ed25519 ' + base64.b64encode(blob).decode()
        self.trust.write_text(f'{ADDRESS} {public}\n')
        self.original[self.trust] = self.trust.read_bytes()
        with self.assertRaisesRegex(HELPER.Stop, 'another host-key type'):
            self.execute([ADDRESS])
        self.assertFalse(self.ssh_calls)
        self.unchanged()

    def test_first_use_mode_failed_login_saves_nothing(self):
        self.args.trust_on_first_use = True
        self.ssh_status = 255
        with self.assertRaisesRegex(HELPER.Stop, 'SSH probe failed'):
            self.execute([ADDRESS])
        self.unchanged()

    def test_first_use_mode_cancel_saves_nothing(self):
        self.args.trust_on_first_use = True
        self.execute([ADDRESS, '', 'n'])
        self.unchanged()

    def test_enterprise_linux_and_operator_alias(self):
        self.info.update(id='rhel', version='9.8')
        self.execute([ADDRESS, FP1, 'work-rhel', 'yes'])
        self.assertIn(f'[enterprise_linux]\nwork-rhel ansible_host={ADDRESS}', self.inventory.read_text())

    def test_decline_does_not_save_inventory_or_trust(self):
        self.execute([ADDRESS, FP1, '', 'n'])
        self.unchanged()

    def test_bad_address_does_not_scan(self):
        for value in ('localhost', ADDRESS + '/24', '127.0.0.1', '-oProxyCommand=bad'):
            with self.subTest(value=value), self.assertRaises(HELPER.Stop):
                self.execute([value])
            self.unchanged()
        self.assertFalse(self.ssh_calls)

    def test_wrong_fingerprint_stops_before_authentication(self):
        with self.assertRaisesRegex(HELPER.Stop, 'Fingerprint mismatch'):
            self.execute([ADDRESS, 'SHA256:' + 'A' * 43])
        self.assertFalse(self.ssh_calls)
        self.unchanged()

    def test_scan_failure_stops_without_changes(self):
        self.scan = ''
        with self.assertRaisesRegex(HELPER.Stop, 'No unique RSA'):
            self.execute([ADDRESS])
        self.unchanged()

    def test_authentication_failure_never_persists_new_trust(self):
        self.ssh_status = 255
        with self.assertRaisesRegex(HELPER.Stop, 'SSH probe failed'):
            self.execute([ADDRESS, FP1])
        self.unchanged()

    def test_existing_mismatched_rsa_stops_before_authentication(self):
        self.trust.write_text(self.trust.read_text() + f'{ADDRESS} {PUB2}\n')
        self.original[self.trust] = self.trust.read_bytes()
        with self.assertRaisesRegex(HELPER.Stop, 'differs from existing trust'):
            self.execute([ADDRESS])
        self.assertFalse(self.ssh_calls)
        self.unchanged()

    def test_existing_hashed_trust_is_reused(self):
        self.trust.write_text(self.trust.read_text() + self.scan)
        subprocess.run(['ssh-keygen', '-H', '-f', str(self.trust)], check=True, capture_output=True)
        self.original[self.trust] = self.trust.read_bytes()
        self.execute([ADDRESS, '', 'y'])
        self.assertEqual(self.trust.read_bytes(), self.original[self.trust])
        self.assertEqual(len(list(self.root.rglob('*.before-add-*'))), 1)

    def test_revoked_host_key_stops(self):
        self.trust.write_text(f'@revoked {ADDRESS} {PUB1}\n')
        self.original[self.trust] = self.trust.read_bytes()
        with self.assertRaisesRegex(HELPER.Stop, 'marker'):
            self.execute([ADDRESS])
        self.unchanged()

    def test_unsupported_os_stops(self):
        self.info['version'] = '22.04'
        with self.assertRaisesRegex(HELPER.Stop, 'Supported targets'):
            self.execute([ADDRESS, FP1])
        self.unchanged()

    def test_conflicts_and_missing_lab_membership_leave_trust_unchanged(self):
        for extra in (f'other-name ansible_host="{ADDRESS}"\n',
                      f'new-host ansible_host={TEST_NET}.99\n', f'{ADDRESS}\n'):
            self.inventory.write_bytes(self.original[self.inventory])
            self.inventory.write_text(self.inventory.read_text().replace('[ubuntu]\n', '[ubuntu]\n' + extra))
            before = self.inventory.read_bytes()
            with self.assertRaises(HELPER.Stop):
                self.execute([ADDRESS, FP1, ''])
            self.assertEqual(self.inventory.read_bytes(), before)
            self.assertEqual(self.trust.read_bytes(), self.original[self.trust])
            self.assertFalse(list(self.root.rglob('*.before-add-*')))
        self.inventory.write_bytes(self.original[self.inventory].replace(b'\nubuntu\n', b'\n'))
        with self.assertRaisesRegex(HELPER.Stop, 'lab:children'):
            self.execute([ADDRESS, FP1, ''])
        self.assertEqual(self.trust.read_bytes(), self.original[self.trust])

    def test_hostname_equal_to_child_group_is_valid(self):
        self.info['hostname'] = 'ubuntu'
        self.execute()
        self.assertIn(f'ubuntu ansible_host={ADDRESS}', self.inventory.read_text())

    def test_file_lock_prevents_concurrent_helper(self):
        with contextlib.ExitStack() as stack:
            HELPER.lock_file(stack, self.inventory)
            with self.assertRaisesRegex(HELPER.Stop, 'Another helper'):
                self.execute([ADDRESS])
        self.unchanged()

    def test_concurrent_unlocked_edit_is_preserved_and_rejected(self):
        replies = iter([ADDRESS, FP1, '', 'y'])
        def answer(prompt):
            if prompt.startswith('Save '):
                self.inventory.write_text(self.inventory.read_text() + '# another editor\n')
            return next(replies)
        with mock.patch.object(HELPER, 'run', side_effect=self.run_command), \
                mock.patch('builtins.input', side_effect=answer), \
                contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaisesRegex(HELPER.Stop, 'changed during this session'):
            HELPER.add_target(self.args)
        self.assertTrue(self.inventory.read_text().endswith('# another editor\n'))
        self.assertEqual(self.trust.read_bytes(), self.original[self.trust])
        self.assertFalse(list(self.root.rglob('*.before-add-*')))

    def test_failed_second_write_rolls_back_first(self):
        real_write = HELPER.write_handle
        attempts = []
        def write(handle, content):
            attempts.append(content)
            if len(attempts) == 2:
                raise OSError('simulated write failure')
            return real_write(handle, content)
        with mock.patch.object(HELPER, 'write_handle', side_effect=write), self.assertRaises(OSError):
            self.execute()
        for path, content in self.original.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(len(list(self.root.rglob('*.before-add-*'))), 2)

    def test_symlink_inventory_refused(self):
        real = self.root / 'real-inventory'
        self.inventory.rename(real)
        self.inventory.symlink_to(real)
        with self.assertRaises(OSError):
            self.execute()
        self.unchanged()

    def test_exposed_private_key_refused(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(HELPER.Stop, 'permissions'):
            self.execute()
        self.unchanged()


if __name__ == '__main__':
    unittest.main()
