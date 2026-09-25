"""Linux-only fixed canary helper regression; never accesses the real interface."""
import base64
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from tests.test_real_awg import CONFIG, DISPOSABLE, ORIGINAL
from tests.test_real_create import EXPECTED_OBFUSCATION

PROFILE = (ORIGINAL, b'127.0.0.2/32', 'panel.example', '127.0.0.1', EXPECTED_OBFUSCATION,
           '127.0.0.1/24', 51820)

if os.name == 'posix':
    from awg_cita import canary_helper as helper
    from awg_cita.real_awg import PersistentCanaryConfig


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'requires isolated Linux root fixture')
class FixedCanaryHelperTests(unittest.TestCase):
    def test_protected_profile_requires_root_owned_private_file(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as root:
            directory = Path(root)
            directory.chmod(0o700)
            profile = directory / 'protected-peer.json'
            value = {'public_key': ORIGINAL, 'route': '127.0.0.2/32',
                     'endpoint_host': 'panel.example', 'dns_server': '127.0.0.1',
                     'obfuscation': EXPECTED_OBFUSCATION,
                     'interface_address': '127.0.0.1/24', 'listen_port': 51820}
            profile.write_text(json.dumps(value), encoding='ascii')
            profile.chmod(0o600)
            with patch.object(helper, 'PROTECTED_PROFILE_FILE', profile):
                self.assertEqual(helper._protected_peer_profile(), PROFILE)
                profile.chmod(0o644)
                with self.assertRaisesRegex(ValueError, 'unsafe canary file'):
                    helper._protected_peer_profile()
                profile.chmod(0o600)
                profile.write_text('{"public_key":"first","public_key":"second"}', encoding='ascii')
                with self.assertRaisesRegex(ValueError, 'duplicate protected profile field'):
                    helper._protected_peer_profile()

    def test_original_key_route_swap_fails_closed(self):
        swapped = CONFIG.replace(b'AllowedIPs = 127.0.0.2/32', b'AllowedIPs = 127.0.0.99/32', 1)
        swapped = swapped.replace(b'AllowedIPs = 127.0.1.254/32', b'AllowedIPs = 127.0.0.2/32', 1)
        with patch.object(helper, '_read_config', return_value=swapped), \
                patch.object(helper, '_protected_peer_profile', return_value=PROFILE):
            with self.assertRaisesRegex(ValueError, 'protected original peer drift'):
                helper._controller()

    def test_original_drift_between_controller_and_operation_read_fails_closed(self):
        swapped = CONFIG.replace(b'AllowedIPs = 127.0.0.2/32', b'AllowedIPs = 127.0.0.99/32', 1)
        swapped = swapped.replace(b'AllowedIPs = 127.0.1.254/32', b'AllowedIPs = 127.0.0.2/32', 1)
        with patch.object(helper, '_read_config', side_effect=[CONFIG, swapped]), \
                patch.object(helper, '_protected_peer_profile', return_value=PROFILE):
            controller = helper._controller()
            with self.assertRaisesRegex(ValueError, 'protected original peer drift'):
                controller._read_config()

    def test_lock_contention_has_bounded_timeout(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as root:
            clock = iter((0, 1, 6))
            with patch.object(helper, 'LOCK', Path(root) / 'lock'), \
                    patch.object(helper.fcntl, 'flock', side_effect=BlockingIOError), \
                    patch.object(helper.time, 'monotonic', side_effect=lambda: next(clock)), \
                    patch.object(helper.time, 'sleep', return_value=None):
                with self.assertRaises(TimeoutError):
                    with helper._locked():
                        self.fail('lock acquired')

    def test_invalid_create_input_never_takes_root_config_lock(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b'not-json')
            os.close(write_fd)
            write_fd = -1
            with patch.object(helper, '_locked', side_effect=AssertionError('lock taken')) as locked, \
                    patch.object(helper.sys, 'stdin', SimpleNamespace(fileno=lambda: read_fd)), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(helper.main(['create']), 1)
            locked.assert_not_called()
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    def test_restart_recovers_only_canary_start_limit(self):
        outcomes = [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0, stdout=b'start-limit-hit\n'),
                    SimpleNamespace(returncode=0), SimpleNamespace(returncode=0)]
        with patch.object(helper.subprocess, 'run', side_effect=outcomes) as run:
            helper._sync_runtime()
        self.assertEqual([call.args[0][1] for call in run.call_args_list],
                         ['restart', 'show', 'reset-failed', 'start'])

    def test_restart_does_not_reset_unrelated_failure(self):
        outcomes = [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0, stdout=b'exit-code\n')]
        with patch.object(helper.subprocess, 'run', side_effect=outcomes) as run:
            with self.assertRaisesRegex(ValueError, 'canary restart failed'):
                helper._sync_runtime()
        self.assertEqual(run.call_count, 2)

    def test_only_disposable_mutates_and_cas_backups_survive_restart(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as root:
            directory = Path(root)
            config = directory / 'awg-canary0.conf'
            config.write_bytes(CONFIG)
            config.chmod(0o600)
            lock = directory / 'lock'
            backups = directory / 'backups'
            state = {'active': {ORIGINAL, DISPOSABLE}}
            def sync():
                state['active'] = {key for key, status in PersistentCanaryConfig(config.read_bytes()).peers().items() if status == 'enabled'}
            def dump():
                interface = ['fixture-private', 'fixture-public', '51820'] + ['0'] * 26
                rows = [[key, '', '', '127.0.0.2/32' if key == ORIGINAL else '127.0.1.254/32', '0', '0', '0', 'off'] for key in sorted(state['active'])]
                return '\n'.join(['\t'.join(interface)] + ['\t'.join(row) for row in rows]) + '\n'
            def call(*args):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    status = helper.main(list(args))
                self.assertEqual(status, 0)
                import json
                return json.loads(output.getvalue())
            peer_id = 'peer-' + hashlib.sha256(base64.b64decode(DISPOSABLE)).hexdigest()[:16]
            original_id = 'peer-' + hashlib.sha256(base64.b64decode(ORIGINAL)).hexdigest()[:16]
            original_block = PersistentCanaryConfig(CONFIG)._entries[ORIGINAL][2]
            with patch.object(helper, 'CONFIG', config), patch.object(helper, 'LOCK', lock), patch.object(helper, 'BACKUPS', backups), patch.object(helper, '_read_dump', dump), patch.object(helper, '_sync_runtime', sync), patch.object(helper, '_protected_peer_profile', return_value=PROFILE):
                self.assertEqual(call('disable', peer_id)['client']['status'], 'DISABLED')
                sync()
                self.assertEqual(call('list')['clients'][1]['status'], 'DISABLED')
                self.assertEqual(call('enable', peer_id)['client']['status'], 'NEVER')
                sync()
                self.assertEqual(call('delete', peer_id)['deleted'], True)
                sync()
                self.assertEqual(len(call('list')['clients']), 1)
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(helper.main(['disable', original_id]), 1)
                self.assertEqual(PersistentCanaryConfig(config.read_bytes())._entries[ORIGINAL][2], original_block)
                self.assertEqual(len(list(backups.glob('*.conf'))), 3)
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_cas_rejects_drift_without_replacing_external_bytes(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as root:
            config = Path(root) / 'awg-canary0.conf'
            config.write_bytes(CONFIG + b'# external\n')
            config.chmod(0o600)
            with patch.object(helper, 'CONFIG', config), patch.object(helper, 'BACKUPS', Path(root) / 'backups'):
                with self.assertRaisesRegex(ValueError, 'config drift'):
                    helper._write_config(CONFIG, PersistentCanaryConfig(CONFIG).disable(DISPOSABLE))
            self.assertEqual(config.read_bytes(), CONFIG + b'# external\n')
