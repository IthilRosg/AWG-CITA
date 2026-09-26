import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from awg_cita.server_endpoint import revision
from awg_cita.server_port import (apply_port, preflight_firewall, recover_pending, replace_config_port,
                                  replace_metadata_port, validate_request, _start_journal)


CONFIG = b'[Interface]\nAddress = 127.0.0.1/24\nListenPort = 47193\nPrivateKey = SYNTHETIC\n'


class PortTests(unittest.TestCase):
    def test_config_replacement_preserves_other_fields(self):
        changed = replace_config_port(CONFIG, 47193, 48193)
        self.assertEqual(changed, CONFIG.replace(b'ListenPort = 47193', b'ListenPort = 48193'))
        self.assertEqual(replace_config_port(changed, 48193, 47193), CONFIG)
        for bad in (CONFIG.replace(b'47193', b'47194'), CONFIG + b'ListenPort = 47193\n'):
            with self.assertRaises(ValueError):
                replace_config_port(bad, 47193, 48193)

    def test_request_rejects_invalid_ports(self):
        expected = 'a' * 64
        self.assertEqual(validate_request({'expectedRevision': expected, 'listenPort': 48193}), (expected, 48193))
        for port in (0, 65536, True, '48193', None):
            with self.subTest(port=port), self.assertRaises(ValueError):
                validate_request({'expectedRevision': expected, 'listenPort': port})

    def test_preflight_accepts_actual_ufw_status_format(self):
        probe = MagicMock()
        probe.__enter__.return_value = probe
        status = b'Status: active\n47193/udp ALLOW Anywhere # AWG-CITA awg2\n'
        with patch('awg_cita.server_port.socket.socket', return_value=probe), \
             patch('awg_cita.server_port._run', return_value=status):
            preflight_firewall(47193, 48193)
            probe.bind.assert_called_with(('0.0.0.0', 48193))

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                         'root-owned files required')
    def test_apply_and_rollback_on_runtime_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            metadata = root / 'profile.json'
            original = b'{"endpoint_host":"old.example.org","listen_port":47193}\n'
            metadata.write_bytes(original)
            metadata.chmod(0o600)
            state = {'config': CONFIG, 'runtime': 47193, 'opened': False, 'fail': False}

            def write_config(expected, replacement):
                self.assertEqual(state['config'], expected)
                state['config'] = replacement

            def sync_runtime():
                port = int(state['config'].split(b'ListenPort = ', 1)[1].splitlines()[0])
                if state['fail'] and port == 48193:
                    raise RuntimeError('synthetic restart failure')
                state['runtime'] = port

            def verify_runtime(port):
                self.assertEqual(state['runtime'], port)

            def invoke():
                return apply_port(profile='wg', path=metadata, limit=512, config=state['config'],
                                  write_config=write_config, read_config=lambda: state['config'],
                                  settings_port=47193, expected_revision=revision(original), new_port=48193,
                                  verify_settings=lambda: json.loads(metadata.read_bytes()),
                                  sync_runtime=sync_runtime, verify_runtime=verify_runtime)

            def allow(*_args):
                state['opened'] = True

            def remove(*_args):
                state['opened'] = False

            with patch('awg_cita.server_port.BACKUPS', root / 'backups'), \
                 patch('awg_cita.server_port.preflight_firewall'), \
                 patch('awg_cita.server_port.allow_port', side_effect=allow), \
                 patch('awg_cita.server_port.remove_new_port', side_effect=remove):
                state['fail'] = True
                with self.assertRaises(RuntimeError):
                    invoke()
                self.assertEqual(state['config'], CONFIG)
                self.assertEqual(metadata.read_bytes(), original)
                self.assertEqual(state['runtime'], 47193)
                self.assertFalse(state['opened'])
                state['fail'] = False
                new_revision = invoke()
                self.assertEqual(new_revision, revision(metadata.read_bytes()))
                self.assertEqual(state['runtime'], 48193)
                self.assertTrue(state['opened'])

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                         'root-owned files required')
    def test_interrupted_migration_restores_old_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            metadata = root / 'profile.json'
            original = b'{"endpoint_host":"old.example.org","listen_port":47193}\n'
            metadata.write_bytes(original)
            metadata.chmod(0o600)
            state = {'config': CONFIG, 'runtime': 47193, 'opened': True}

            def write_config(expected, replacement):
                self.assertEqual(state['config'], expected)
                state['config'] = replacement

            def sync_runtime():
                state['runtime'] = int(state['config'].split(b'ListenPort = ', 1)[1].splitlines()[0])

            with patch('awg_cita.server_port.BACKUPS', root / 'backups'), \
                 patch('awg_cita.server_port._run', return_value=b'Status: active\n48193/udp ALLOW IN Anywhere # AWG-CITA wg\n'), \
                 patch('awg_cita.server_port.remove_new_port', side_effect=lambda _port: state.update(opened=False)):
                _start_journal('wg', 47193, 48193, CONFIG, original)
                state['config'] = replace_config_port(CONFIG, 47193, 48193)
                replace_metadata_port(metadata, profile='wg', expected_revision=revision(original),
                                      old=47193, new=48193, limit=512, verify=lambda: None)
                state['runtime'] = 48193
                restored = recover_pending(profile='wg', path=metadata, limit=512,
                                           read_config=lambda: state['config'], write_config=write_config,
                                           sync_runtime=sync_runtime,
                                           verify_runtime=lambda port: self.assertEqual(state['runtime'], port))
                self.assertTrue(restored)
                self.assertEqual(metadata.read_bytes(), original)
                self.assertEqual(state['config'], CONFIG)
                self.assertEqual(state['runtime'], 47193)
                self.assertFalse(state['opened'])
                self.assertFalse((root / 'backups' / 'wg-port.pending').exists())


if __name__ == '__main__':
    unittest.main()
