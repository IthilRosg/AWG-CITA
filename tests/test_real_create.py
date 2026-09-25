"""Synthetic REAL create path; never uses a live canary or prints key material."""
import base64
import hashlib
import json
import unittest
from unittest.mock import patch

from awg_cita.lifecycle import LifecycleError, LifecycleService
from awg_cita.real_awg import CanaryPeerController as _CanaryPeerController, PersistentCanaryConfig
from tests.test_real_awg import CONFIG, ORIGINAL

CLIENT_PRIVATE = base64.b64encode(bytes(range(32))).decode()
CLIENT_PUBLIC = base64.b64encode(bytes(range(32, 64))).decode()
SERVER_PUBLIC = ORIGINAL
EXPECTED_OBFUSCATION = {'S1': '20', 'S2': '24', 'S3': '28', 'S4': '32',
                        'H1': '1001', 'H2': '1002',
                        'H3': '1003', 'H4': '1004'}


def CanaryPeerController(*args, **kwargs):
    return _CanaryPeerController(*args, endpoint_host='panel.example', dns_server='127.0.0.1',
                                expected_obfuscation=EXPECTED_OBFUSCATION,
                                expected_interface_address='127.0.0.1/24', expected_listen_port=51820,
                                **kwargs)
PROFILE = CONFIG.replace(b'ListenPort = 51820\n', b'ListenPort = 51820\nAddress = 127.0.0.1/24\nS1 = 20\nS2 = 24\nS3 = 28\nS4 = 32\nH1 = 1001\nH2 = 1002\nH3 = 1003\nH4 = 1004\n').split(b'\n[Peer]\n', 2)[0] + b'\n[Peer]\n' + CONFIG.split(b'\n[Peer]\n', 2)[1]


def dump(state):
    header = ['fixture-private', SERVER_PUBLIC, '51820'] + ['0'] * 26
    lines = ['\t'.join(header)]
    for key, (_, _, block) in PersistentCanaryConfig(state['config'])._entries.items():
        if key in state['runtime']:
            route = next(line.split(b'=', 1)[1].strip().decode() for line in block.splitlines() if line.startswith(b'AllowedIPs'))
            lines.append('\t'.join([key, '', '', route, '0', '0', '0', 'off']))
    return '\n'.join(lines) + '\n'


class RelayCreateTests(unittest.TestCase):
    def test_sudoers_grants_only_fixed_create_helper_entry(self):
        from pathlib import Path
        rule = Path('scripts/awg-cita-canary.sudoers').read_text(encoding='ascii')
        self.assertIn('/usr/local/sbin/awg-cita-peer create', rule)
        self.assertNotIn('/usr/local/sbin/awg-cita-peer create *', rule)
        self.assertNotIn('NOPASSWD: ALL', rule)
        wrapper = Path('scripts/awg-cita-peer').read_text(encoding='ascii')
        self.assertIn("/opt/awg-cita/current/site", wrapper)

    @unittest.skipUnless(__import__('os').name == 'posix', 'Unix relay requires POSIX Python')
    def test_fixed_create_route_is_forwarded_only_with_trusted_headers(self):
        from tests.test_rate_limit_proxy import RateLimitRelayTests, Backend, COOKIE, HOST
        case = RateLimitRelayTests('test_public_get_carries_only_application_session_to_backend')
        case.setUp()
        try:
            request = json.dumps({'name': 'New Device', 'tags': [], 'idempotencyKey': 'request-0001', 'acknowledged': True}).encode()
            headers = {'Cookie': COOKIE, 'Origin': 'https://' + HOST + ':8444', 'X-CSRF-Token': 'synthetic-csrf', 'Content-Type': 'application/json'}
            self.assertEqual(case.request('POST', '/api/clients', request, headers)[0], 403)
            self.assertEqual(len(Backend.posts), 1)
            self.assertEqual(case.raw_status('POST', '/api/clients?trick=1', request, headers), 404)
            self.assertEqual(len(Backend.posts), 1)
        finally:
            case.tearDown()


class AdapterCreateTests(unittest.TestCase):
    def test_existing_reader_import_does_not_depend_on_qr_package(self):
        import subprocess
        import sys
        script = (
            'import builtins\n'
            'original = builtins.__import__\n'
            'def guarded(name, *args, **kwargs):\n'
            '    if name == "segno": raise ImportError("qr unavailable")\n'
            '    return original(name, *args, **kwargs)\n'
            'builtins.__import__ = guarded\n'
            'from awg_cita.real_awg import PersistentCanaryConfig\n'
            'assert PersistentCanaryConfig\n'
        )
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, 'read-only canary import must remain available without QR dependency')

    def test_malformed_helper_output_has_no_secret_exception_context(self):
        from awg_cita.real_awg import RealAwgLifecycleAdapter
        from awg_cita.app import AwgReader
        from unittest.mock import patch
        with patch.object(AwgReader, '_run', return_value=('not-json-sensitive-output', '')):
            with self.assertRaises(LifecycleError) as raised:
                RealAwgLifecycleAdapter().create_client('New Device', [], 'request-0009')
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_fixed_helper_create_operation_and_response(self):
        from awg_cita.real_awg import RealAwgLifecycleAdapter
        from unittest.mock import patch
        from awg_cita.app import AwgReader
        import json
        record = {'id': 'peer-0123456789abcdef', 'name': 'New Device', 'status': 'NEVER', 'lastHandshakeAt': None, 'lastSeenAt': None, 'createdAt': None, 'expiration': '', 'rxBytes': 0, 'txBytes': 0, 'notes': '', 'tags': [], 'warning': ''}
        reply = {'schema_version': 1, 'client': record, 'configText': 'secret-fixture', 'qrDataUri': 'data:image/png;base64,Zml4dHVyZQ==', 'oneTime': True}
        with patch.object(AwgReader, '_run', return_value=(json.dumps(reply), '')) as run:
            result = RealAwgLifecycleAdapter().create_client('New Device', [], 'request-0001')
        self.assertEqual(result['oneTime'], True)
        argv, timeout, body = run.call_args.args
        self.assertEqual(argv, ('/usr/bin/sudo', '-n', '--', '/usr/local/sbin/awg-cita-peer', 'create'))
        self.assertEqual(json.loads(body), {'name': 'New Device', 'tags': [], 'idempotencyKey': 'request-0001'})
        self.assertEqual(timeout, 300)
        self.assertNotIn(CLIENT_PRIVATE, repr(argv))


class ServiceCreateTests(unittest.TestCase):
    def test_adapter_failure_does_not_attach_private_error(self):
        class BrokenAdapter:
            def create_client(self, *args):
                raise ValueError('secret-fixture')
        service = LifecycleService(BrokenAdapter())
        with self.assertRaises(LifecycleError) as raised:
            service.create_client('New Device', [], 'request-0010', True)
        self.assertIsNone(raised.exception.__context__)
        self.assertIsNone(raised.exception.__cause__)

    def test_create_requires_session_origin_csrf_ack_and_no_store(self):
        from unittest.mock import patch
        from awg_cita.lifecycle import FakeAwgLifecycleAdapter
        from tests.test_real_http import CanaryHttpTests
        class CreatingAdapter(FakeAwgLifecycleAdapter):
            def create_client(self, name, tags, nonce):
                return {'schema_version': 1, 'client': dict(self._clients[0], name=name, tags=tags), 'configText': 'secret-fixture', 'qrDataUri': 'data:image/png;base64,Zml4dHVyZQ==', 'oneTime': True}
        case = CanaryHttpTests('test_bad_methods_content_and_payload_fail_without_mutation')
        case.setUp()
        try:
            case.server.RequestHandlerClass.lifecycle_service = LifecycleService(CreatingAdapter([{'id': 'peer-0123456789abcdef', 'name': 'Test Peer', 'status': 'NEVER', 'lastHandshakeAt': None, 'lastSeenAt': None, 'createdAt': None, 'expiration': '', 'rxBytes': 0, 'txBytes': 0, 'notes': '', 'tags': [], 'warning': ''}]))
            payload = json.dumps({'name': 'New Device', 'tags': [], 'idempotencyKey': 'request-0001', 'acknowledged': True})
            self.assertEqual(case.request('POST', '/api/clients', payload, {'Content-Type': 'application/json'})[0], 401)
            _, headers, html = case.request('GET', '/')
            import re
            csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
            trusted = {'Cookie': headers['Set-Cookie'].split(';', 1)[0], 'Origin': case.origin, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}
            self.assertEqual(case.request('POST', '/api/clients', payload, dict(trusted, Origin='https://attacker.invalid'))[0], 403)
            status, response_headers, body = case.request('POST', '/api/clients', payload, trusted)
            self.assertEqual(status, 200)
            self.assertEqual(response_headers['Cache-Control'], 'no-store')
            self.assertEqual(json.loads(body)['oneTime'], True)
            self.assertEqual(case.request('POST', '/api/clients', payload, trusted)[0], 409)
        finally:
            case.tearDown()

    def test_no_cache_or_audit_contains_one_time_material(self):
        class Adapter:
            def __init__(self):
                self.calls = 0
            def create_client(self, name, tags, nonce):
                self.calls += 1
                return {'schema_version': 1, 'client': {'id': 'peer-0123456789abcdef', 'name': name, 'status': 'NEVER', 'lastHandshakeAt': None, 'lastSeenAt': None, 'createdAt': None, 'expiration': '', 'rxBytes': 0, 'txBytes': 0, 'notes': '', 'tags': tags, 'warning': ''}, 'configText': 'secret-fixture', 'qrDataUri': 'data:image/png;base64,Zml4dHVyZQ==', 'oneTime': True}
        adapter = Adapter()
        service = LifecycleService(adapter)
        result = service.create_client('New Device', [], 'request-0001', True)
        self.assertEqual(result['oneTime'], True)
        self.assertFalse('secret-fixture' in repr(service.__dict__))
        self.assertFalse('data:image/png' in repr(service.__dict__))
        with self.assertRaises(LifecycleError):
            service.create_client('New Device', [], 'request-0001', True)
        self.assertEqual(adapter.calls, 1)
        with self.assertRaises(LifecycleError):
            service.create_client('New Device', [], 'request-0002', False)


class RealCreateTests(unittest.TestCase):
    def test_create_preserves_repeated_awg_hook_commands(self):
        hooks = b'PostUp = true\nPostUp = true\nPostDown = true\nPostDown = true\n'
        profile = PROFILE.replace(b'ListenPort = 51820\n', b'ListenPort = 51820\n' + hooks)
        state = {'config': profile, 'runtime': set(PersistentCanaryConfig(profile).peers())}
        def cas(before, after):
            self.assertEqual(before, state['config'])
            state['config'] = after
        def sync():
            state['runtime'] = {key for key, status in PersistentCanaryConfig(state['config']).peers().items() if status == 'enabled'}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=cas, sync_runtime=sync)
        with patch('segno.make_qr') as qr:
            qr.return_value.png_data_uri.return_value = 'data:image/png;base64,Zml4dHVyZQ=='
            result = controller.create('New Device', [], 'request-hooks-01',
                                       lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)
        self.assertTrue(result['oneTime'])
        self.assertIn(hooks, state['config'])
        self.assertEqual(state['config'].count(b'PostUp = true\n'), 2)
        self.assertEqual(state['config'].count(b'PostDown = true\n'), 2)

    def test_create_still_rejects_duplicate_profile_field(self):
        profile = PROFILE.replace(b'Address = 127.0.0.1/24\n', b'Address = 127.0.0.1/24\n' * 2)
        state = {'config': profile, 'runtime': set(PersistentCanaryConfig(profile).peers())}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state),
                                          write_config=lambda *_: self.fail('unexpected write'), sync_runtime=lambda: None)
        with self.assertRaisesRegex(ValueError, 'duplicate canary interface field'):
            controller.create('New Device', [], 'request-hooks-02',
                              lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)

    def test_create_returns_one_time_config_and_persists_only_public_peer(self):
        state = {'config': PROFILE, 'runtime': set(PersistentCanaryConfig(PROFILE).peers()), 'writes': 0}
        def cas(before, after):
            self.assertTrue(state['config'] == before)
            state['config'] = after
            state['writes'] += 1
        def sync():
            state['runtime'] = {key for key, status in PersistentCanaryConfig(state['config']).peers().items() if status == 'enabled'}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=cas, sync_runtime=sync)
        with patch('segno.make_qr') as qr:
            qr.return_value.png_data_uri.return_value = 'data:image/png;base64,Zml4dHVyZQ=='
            result = controller.create('New Device', ['mobile'], 'request-0001', lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)
            self.assertTrue(qr.call_args.args[0] == result['configText'])
        self.assertEqual(result['oneTime'], True)
        self.assertEqual(result['schema_version'], 1)
        self.assertTrue(result['qrDataUri'] == 'data:image/png;base64,Zml4dHVyZQ==')
        self.assertTrue('Address = 127.0.0.3/32' in result['configText'])
        self.assertTrue('AllowedIPs = 0.0.0.0/0' in result['configText'])
        self.assertTrue('DNS = 127.0.0.1' in result['configText'])
        self.assertTrue('Endpoint = panel.example:51820' in result['configText'])
        self.assertTrue('S1 = 20' in result['configText'])
        self.assertFalse('Jc =' in result['configText'])
        self.assertFalse(CLIENT_PRIVATE.encode() in state['config'])
        self.assertFalse(b'data:image' in state['config'])
        self.assertTrue(CLIENT_PUBLIC.encode() in state['config'])
        self.assertEqual(state['writes'], 1)
        self.assertEqual(controller.list_clients()[-1]['name'], 'New Device')
        self.assertEqual(controller.list_clients()[-1]['tags'], ['mobile'])
        mutable = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=cas,
                                       sync_runtime=sync, mutable_keys={CLIENT_PUBLIC})
        self.assertEqual(mutable.mutate('disable', result['client']['id'])['status'], 'DISABLED')
        self.assertEqual(mutable.list_clients()[-1]['name'], 'New Device')
        self.assertEqual(mutable.mutate('enable', result['client']['id'])['name'], 'New Device')
        with self.assertRaises(ValueError):
            controller.create('New Device', ['mobile'], 'request-0001', lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)
        self.assertEqual(state['writes'], 3)
        state['config'] = PersistentCanaryConfig(state['config']).delete(CLIENT_PUBLIC)
        sync()
        restarted = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=cas, sync_runtime=sync)
        with self.assertRaises(ValueError):
            restarted.create('New Device', ['mobile'], 'request-0001', lambda: self.fail('replay generated a key'), lambda: SERVER_PUBLIC)

    def test_disabled_peer_route_is_reserved_during_allocation(self):
        from tests.test_real_awg import DISPOSABLE
        occupied = PROFILE + b'\n[Peer]\nPublicKey = ' + DISPOSABLE.encode('ascii') + b'\nAllowedIPs = 127.0.0.3/32\n'
        occupied = PersistentCanaryConfig(occupied).disable(DISPOSABLE)
        state = {'config': occupied, 'runtime': {ORIGINAL}}
        def cas(before, after):
            self.assertTrue(state['config'] == before)
            state['config'] = after
        def sync():
            state['runtime'] = {key for key, status in PersistentCanaryConfig(state['config']).peers().items() if status == 'enabled'}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=cas, sync_runtime=sync)
        with patch('segno.make_qr') as qr:
            qr.return_value.png_data_uri.return_value = 'data:image/png;base64,Zml4dHVyZQ=='
            result = controller.create('New Device', [], 'request-0008', lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)
        self.assertTrue('Address = 127.0.0.4/32' in result['configText'])
        self.assertEqual(PersistentCanaryConfig(state['config']).peers()[DISPOSABLE], 'disabled')

    def test_overlapping_broad_route_skips_first_candidate(self):
        profile = PROFILE.replace(b'AllowedIPs = 127.0.0.2/32\n', b'AllowedIPs = 127.0.0.2/31\n')
        state = {'config': profile, 'runtime': set(PersistentCanaryConfig(profile).peers())}
        def cas(before, after):
            self.assertEqual(state['config'], before)
            state['config'] = after
        def sync():
            state['runtime'] = {key for key, status in PersistentCanaryConfig(state['config']).peers().items() if status == 'enabled'}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=cas, sync_runtime=sync)
        with patch('segno.make_qr') as qr:
            qr.return_value.png_data_uri.return_value = 'data:image/png;base64,'
            result = controller.create('New Device', [], 'request-0012', lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)
        self.assertIn('Address = 127.0.0.4/32', result['configText'])
        self.assertIn(b'AllowedIPs = 127.0.0.4/32\n', state['config'])
        self.assertIn(b'AllowedIPs = 127.0.0.2/31\n', state['config'])

    def test_server_public_mismatch_fails_before_mutation(self):
        state = {'config': PROFILE, 'runtime': set(PersistentCanaryConfig(PROFILE).peers())}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=lambda *_: self.fail('write'), sync_runtime=lambda: self.fail('sync'))
        with self.assertRaises(ValueError):
            controller.create('New Device', [], 'request-0007', lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: base64.b64encode(bytes(range(128, 160))).decode())

    def test_unexpected_obfuscation_value_fails_before_key_generation(self):
        profile = PROFILE.replace(b'S1 = 20\n', b'S1 = 21\n')
        state = {'config': profile, 'runtime': set(PersistentCanaryConfig(profile).peers())}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=lambda *_: self.fail('write'), sync_runtime=lambda: self.fail('sync'))
        with self.assertRaises(ValueError):
            controller.create('New Device', [], 'request-0006', lambda: self.fail('key generation'), lambda: SERVER_PUBLIC)

    def test_interface_address_drift_fails_before_key_generation(self):
        profile = PROFILE.replace(b'Address = 127.0.0.1/24\n', b'Address = 127.0.1.1/24\n')
        state = {'config': profile, 'runtime': set(PersistentCanaryConfig(profile).peers())}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state),
                                          write_config=lambda *_: self.fail('write'),
                                          sync_runtime=lambda: self.fail('sync'))
        with self.assertRaisesRegex(ValueError, 'unexpected canary profile'):
            controller.create('New Device', [], 'request-0014', lambda: self.fail('key generation'),
                              lambda: SERVER_PUBLIC)

    def test_invalid_optional_j_range_fails_before_key_generation(self):
        profile = PROFILE.replace(b'H4 = 1004\n', b'H4 = 1004\nJc = 65536\nJmin = 10\nJmax = 20\n')
        state = {'config': profile, 'runtime': set(PersistentCanaryConfig(profile).peers())}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=lambda *_: self.fail('write'), sync_runtime=lambda: self.fail('sync'))
        with self.assertRaises(ValueError):
            controller.create('New Device', [], 'request-0011', lambda: self.fail('key generation'), lambda: SERVER_PUBLIC)

    def test_partial_j_profile_fails_before_key_generation(self):
        profile = PROFILE.replace(b'H4 = 1004\n', b'H4 = 1004\nJc = 4\n')
        state = {'config': profile, 'runtime': set(PersistentCanaryConfig(profile).peers())}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=lambda *_: self.fail('write'), sync_runtime=lambda: self.fail('sync'))
        with self.assertRaises(ValueError):
            controller.create('New Device', [], 'request-0003', lambda: self.fail('key generation'), lambda: SERVER_PUBLIC)

    def test_restart_failure_rolls_back_and_never_returns_secret(self):
        state = {'config': PROFILE, 'runtime': set(PersistentCanaryConfig(PROFILE).peers()), 'writes': 0}
        def cas(before, after):
            self.assertTrue(state['config'] == before)
            state['config'] = after
            state['writes'] += 1
        def sync():
            if state['writes'] == 1:
                raise ValueError('ambiguous restart')
            state['runtime'] = {key for key, status in PersistentCanaryConfig(state['config']).peers().items() if status == 'enabled'}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=cas, sync_runtime=sync)
        with patch('segno.make_qr') as qr:
            qr.return_value.png_data_uri.return_value = 'data:image/png;base64,Zml4dHVyZQ=='
            with self.assertRaises(ValueError):
                controller.create('New Device', [], 'request-0004', lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)
        self.assertTrue(state['config'] == PROFILE)
        self.assertEqual(state['writes'], 2)

    def test_ambiguous_post_replace_write_rolls_back_create_and_mutation(self):
        from tests.test_real_awg import DISPOSABLE
        for operation in ('create', 'disable'):
            with self.subTest(operation=operation):
                initial = PROFILE if operation == 'create' else PROFILE + (
                    b'\n[Peer]\nPublicKey = ' + DISPOSABLE.encode('ascii') + b'\nAllowedIPs = 127.0.0.4/32\n')
                state = {'config': initial, 'runtime': set(PersistentCanaryConfig(initial).peers()), 'writes': 0}
                def cas(before, after):
                    self.assertEqual(state['config'], before)
                    state['config'] = after
                    state['writes'] += 1
                    if state['writes'] == 1:
                        raise OSError('directory fsync failed after replacement')
                def sync():
                    state['runtime'] = {key for key, status in PersistentCanaryConfig(state['config']).peers().items() if status == 'enabled'}
                controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=cas,
                                                  sync_runtime=sync, mutable_keys={DISPOSABLE})
                with patch('segno.make_qr') as qr:
                    qr.return_value.png_data_uri.return_value = 'data:image/png;base64,Zml4dHVyZQ=='
                    with self.assertRaises(OSError):
                        if operation == 'create':
                            controller.create('New Device', [], 'request-0013',
                                              lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)
                        else:
                            peer_id = 'peer-' + hashlib.sha256(base64.b64decode(DISPOSABLE)).hexdigest()[:16]
                            controller.mutate('disable', peer_id)
                self.assertEqual(state['config'], initial)
                self.assertEqual(state['runtime'], set(PersistentCanaryConfig(initial).peers()))
                self.assertEqual(state['writes'], 2)

    def test_actual_segno_png_matches_exact_text_without_printing_payload(self):
        import segno
        state = {'config': PROFILE, 'runtime': set(PersistentCanaryConfig(PROFILE).peers())}
        def cas(before, after):
            state['config'] = after
        def sync():
            state['runtime'] = {key for key, status in PersistentCanaryConfig(state['config']).peers().items() if status == 'enabled'}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=cas, sync_runtime=sync)
        result = controller.create('New Device', [], 'request-0005', lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)
        self.assertTrue(result['qrDataUri'] == segno.make_qr(result['configText']).png_data_uri(scale=4))
        self.assertTrue(base64.b64decode(result['qrDataUri'].split(',', 1)[1]).startswith(b'\x89PNG\r\n\x1a\n'))

    def test_qr_failure_precedes_write(self):
        state = {'config': PROFILE, 'runtime': set(PersistentCanaryConfig(PROFILE).peers())}
        controller = CanaryPeerController(lambda: state['config'], lambda: dump(state), write_config=lambda *_: self.fail('mutation'), sync_runtime=lambda: self.fail('restart'))
        with patch('segno.make_qr', side_effect=ValueError('qr failed')):
            with self.assertRaises(ValueError):
                controller.create('New Device', [], 'request-0002', lambda: (CLIENT_PRIVATE, CLIENT_PUBLIC), lambda: SERVER_PUBLIC)
        self.assertTrue(state['config'] == PROFILE)
