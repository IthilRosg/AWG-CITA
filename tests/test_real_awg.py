"""Persistent canary peer semantics; no live server mutations in this suite."""
import base64
import unittest
from unittest.mock import patch

from awg_cita.real_awg import PersistentCanaryConfig, RealAwgLifecycleAdapter, CanaryPeerController
from awg_cita.lifecycle import LifecycleService


ORIGINAL = base64.b64encode(bytes(range(64, 96))).decode('ascii')
DISPOSABLE = base64.b64encode(bytes(range(96, 128))).decode('ascii')
CONFIG = (
    '[Interface]\nPrivateKey = fixture-secret-do-not-expose\nListenPort = 51820\n'
    '\n[Peer]\n# existing\nPublicKey = ' + ORIGINAL + '\nAllowedIPs = 127.0.0.2/32\n'
    '\n[Peer]\nPublicKey = ' + DISPOSABLE + '\nAllowedIPs = 127.0.1.254/32\n'
).encode()


class PersistentCanaryConfigTests(unittest.TestCase):
    def test_disable_survives_reparse_and_preserves_unrelated_peer(self):
        config = PersistentCanaryConfig(CONFIG)
        disabled = config.disable(DISPOSABLE)
        parsed = PersistentCanaryConfig(disabled)
        self.assertEqual(parsed.peers(), {ORIGINAL: 'enabled', DISPOSABLE: 'disabled'})
        self.assertNotIn(DISPOSABLE.encode(), parsed.active_config())
        self.assertIn(('PublicKey = ' + ORIGINAL).encode(), parsed.active_config())
        self.assertIn(b'fixture-secret-do-not-expose', parsed.active_config())

    def test_enable_restores_exact_original_stanza(self):
        config = PersistentCanaryConfig(CONFIG)
        self.assertEqual(PersistentCanaryConfig(config.disable(DISPOSABLE)).enable(DISPOSABLE), CONFIG)

    def test_disabled_peer_survives_change_to_adjacent_enabled_peer(self):
        disabled = PersistentCanaryConfig(CONFIG).disable(DISPOSABLE)
        self.assertEqual(PersistentCanaryConfig(PersistentCanaryConfig(disabled).disable(ORIGINAL)).peers(),
                         {ORIGINAL: 'disabled', DISPOSABLE: 'disabled'})
        self.assertEqual(PersistentCanaryConfig(PersistentCanaryConfig(disabled).delete(ORIGINAL)).peers(),
                         {DISPOSABLE: 'disabled'})

    def test_delete_removes_only_target_and_rejects_unknown(self):
        config = PersistentCanaryConfig(CONFIG)
        deleted = config.delete(DISPOSABLE)
        self.assertEqual(PersistentCanaryConfig(deleted).peers(), {ORIGINAL: 'enabled'})
        self.assertIn(('PublicKey = ' + ORIGINAL).encode(), deleted)
        with self.assertRaises(ValueError):
            config.delete(base64.b64encode(bytes(32)).decode('ascii'))

    def test_duplicate_or_malformed_peer_rejected_before_mutation(self):
        with self.assertRaises(ValueError):
            PersistentCanaryConfig(CONFIG + b'\n[Peer]\nPublicKey = ' + ORIGINAL.encode() + b'\n')
        with self.assertRaises(ValueError):
            PersistentCanaryConfig(CONFIG.replace(DISPOSABLE.encode(), b'not-base64'))

    def test_peer_without_single_valid_route_is_not_actionable(self):
        for replacement in (b'AllowedIPs = nonsense', b'AllowedIPs = 127.0.1.254/32\nAllowedIPs = 127.0.0.0/8', b''):
            with self.subTest(replacement=replacement):
                malformed = CONFIG.replace(b'AllowedIPs = 127.0.1.254/32', replacement)
                with self.assertRaises(ValueError):
                    PersistentCanaryConfig(malformed)


class RealAdapterBoundaryTests(unittest.TestCase):
    def test_read_and_disable_use_only_fixed_helper_operations_and_canonical_result(self):
        calls = []
        record = {
            'id': 'peer-8f1e', 'name': 'Peer 8f1e', 'status': 'NEVER',
            'lastHandshakeAt': None, 'lastSeenAt': None, 'createdAt': None,
            'expiration': '', 'rxBytes': 0, 'txBytes': 0, 'notes': '', 'tags': [], 'warning': ''
        }

        def helper(operation, peer_id=None):
            calls.append((operation, peer_id))
            if operation == 'list':
                return {'schema_version': 1, 'clients': [record]}
            return {'schema_version': 1, 'client': dict(record, status='DISABLED')}

        service = LifecycleService(RealAwgLifecycleAdapter(helper))
        self.assertEqual(service.list_clients(), [record])
        updated = service.disable_client('peer-8f1e', 'disable-real-test-01', 'operator_requested')
        self.assertEqual(updated['status'], 'DISABLED')
        self.assertEqual(calls, [('list', None), ('disable', 'peer-8f1e')])

    def test_unknown_or_secret_bearing_helper_record_fails_closed(self):
        record = {
            'id': 'peer-8f1e', 'name': 'Peer 8f1e', 'status': 'NEVER',
            'lastHandshakeAt': None, 'lastSeenAt': None, 'createdAt': None,
            'expiration': '', 'rxBytes': 0, 'txBytes': 0, 'notes': '', 'tags': [], 'warning': ''
        }
        adapter = RealAwgLifecycleAdapter(lambda _op, _id=None: {
            'schema_version': 1,
            'clients': [dict(record, privateKey='must-not-leak')],
        })
        with self.assertRaises(Exception):
            LifecycleService(adapter).list_clients()

    def test_default_transport_uses_fixed_sudo_argv_not_shell(self):
        from awg_cita.app import AwgReader
        with patch.object(AwgReader, '_run', return_value=('{"schema_version":1,"clients":[]}', '')) as run:
            self.assertEqual(RealAwgLifecycleAdapter().list_clients(), [])
        run.assert_called_once_with(
            ('/usr/bin/sudo', '-n', '--', '/usr/local/sbin/awg-cita-peer', 'list'), 15
        )


class CanaryControllerTests(unittest.TestCase):
    def test_read_joins_persistent_peer_to_runtime_without_exposing_public_key(self):
        interface = ['fixture-private', 'fixture-public', '51820'] + ['0'] * 26
        peer = [ORIGINAL, '', '', '127.0.0.2/32', '0', '12', '34', 'off']
        dump = '\n'.join(('\t'.join(interface), '\t'.join(peer))) + '\n'
        controller = CanaryPeerController(lambda: CONFIG.split(b'\n[Peer]\n', 2)[0] + b'\n[Peer]\n' + CONFIG.split(b'\n[Peer]\n', 2)[1], lambda: dump)
        result = controller.list_clients()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'NEVER')
        self.assertEqual(result[0]['createdAt'], None)
        self.assertEqual((result[0]['rxBytes'], result[0]['txBytes']), (12, 34))
        self.assertNotIn(ORIGINAL, repr(result))
        self.assertNotIn('fixture-private', repr(result))

    def test_mutation_persists_only_allowlisted_disposable_and_survives_restart(self):
        import hashlib
        import base64
        state = {'config': CONFIG, 'runtime': {ORIGINAL, DISPOSABLE}}
        def dump():
            interface = ['fixture-private', 'fixture-public', '51820'] + ['0'] * 26
            peers = [[key, '', '', '127.0.0.2/32' if key == ORIGINAL else '127.0.1.254/32', '0', '0', '0', 'off'] for key in state['runtime']]
            return '\n'.join(['\t'.join(interface)] + ['\t'.join(row) for row in peers]) + '\n'
        def sync():
            state['runtime'] = {key for key, status in PersistentCanaryConfig(state['config']).peers().items() if status == 'enabled'}
        def compare_and_swap(expected, replacement):
            if state['config'] != expected:
                raise ValueError('config drift')
            state['config'] = replacement
        controller = CanaryPeerController(lambda: state['config'], dump, write_config=compare_and_swap, sync_runtime=sync, mutable_keys={DISPOSABLE})
        client_id = 'peer-' + hashlib.sha256(base64.b64decode(DISPOSABLE)).hexdigest()[:16]
        original_id = 'peer-' + hashlib.sha256(base64.b64decode(ORIGINAL)).hexdigest()[:16]
        self.assertEqual(controller.mutate('disable', client_id)['status'], 'DISABLED')
        sync()  # simulated service restart reloads only persistent peers
        self.assertEqual(controller.list_clients()[1]['status'], 'DISABLED')
        self.assertEqual(controller.mutate('enable', client_id)['status'], 'NEVER')
        with self.assertRaises(ValueError):
            controller.mutate('delete', original_id)
        self.assertTrue(controller.mutate('delete', client_id)['deleted'])
        self.assertEqual(len(controller.list_clients()), 1)

    def test_config_drift_before_write_fails_without_overwriting_external_change(self):
        import hashlib
        import base64
        state = {'config': CONFIG}
        changed = CONFIG + b'# external marker\n'
        def cas(expected, replacement):
            state['config'] = changed
            if state['config'] != expected:
                raise ValueError('config drift')
            state['config'] = replacement
        interface = ['fixture-private', 'fixture-public', '51820'] + ['0'] * 26
        peers = [[key, '', '', '127.0.0.2/32' if key == ORIGINAL else '127.0.1.254/32', '0', '0', '0', 'off'] for key in (ORIGINAL, DISPOSABLE)]
        dump = '\n'.join(['\t'.join(interface)] + ['\t'.join(row) for row in peers]) + '\n'
        controller = CanaryPeerController(lambda: state['config'], lambda: dump, write_config=cas, sync_runtime=lambda: None, mutable_keys={DISPOSABLE})
        client_id = 'peer-' + hashlib.sha256(base64.b64decode(DISPOSABLE)).hexdigest()[:16]
        with self.assertRaises(ValueError):
            controller.mutate('disable', client_id)
        self.assertEqual(state['config'], changed)

    def test_failed_readback_rolls_back_with_target_as_expected(self):
        import base64
        import hashlib
        state = {'config': CONFIG, 'writes': [], 'syncs': 0}
        def cas(expected, replacement):
            self.assertEqual(state['config'], expected)
            state['writes'].append((expected, replacement))
            state['config'] = replacement
        def sync():
            state['syncs'] += 1
        interface = ['fixture-private', 'fixture-public', '51820'] + ['0'] * 26
        peers = [[key, '', '', '127.0.0.2/32' if key == ORIGINAL else '127.0.1.254/32', '0', '0', '0', 'off'] for key in (ORIGINAL, DISPOSABLE)]
        dump = '\n'.join(['\t'.join(interface)] + ['\t'.join(row) for row in peers]) + '\n'
        controller = CanaryPeerController(lambda: state['config'], lambda: dump, write_config=cas, sync_runtime=sync, mutable_keys={DISPOSABLE})
        client_id = 'peer-' + hashlib.sha256(base64.b64decode(DISPOSABLE)).hexdigest()[:16]
        with self.assertRaisesRegex(ValueError, 'runtime differs from persistent config'):
            controller.mutate('disable', client_id)
        self.assertEqual(state['config'], CONFIG)
        self.assertEqual(state['writes'][0][0], CONFIG)
        self.assertEqual(state['writes'][1], (state['writes'][0][1], CONFIG))
        self.assertEqual(state['syncs'], 2)


if __name__ == '__main__':
    unittest.main()
