"""Focused same-origin canary API/auth/CSRF tests, no live mutations."""
import json
import os
import re
import socket
import stat
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from awg_cita.app import AwgReader, create_server
from awg_cita.lifecycle import FakeAwgLifecycleAdapter, LifecycleService

PEER_ID = 'peer-0123456789abcdef'
RECORD = {
    'id': PEER_ID, 'name': 'Test Peer', 'status': 'NEVER', 'lastHandshakeAt': None,
    'lastSeenAt': None, 'createdAt': None, 'expiration': '', 'rxBytes': 0, 'txBytes': 0,
    'notes': '', 'tags': [], 'warning': ''
}


class CanaryHttpTests(unittest.TestCase):
    def setUp(self):
        reader = AwgReader(binary='/unused', interface='awg-canary0', runner=lambda *_: ('', ''))
        self.server = create_server(reader, '127.0.0.1', 0,
                                    lifecycle_service=LifecycleService(FakeAwgLifecycleAdapter([RECORD])),
                                    operator_origin='http://127.0.0.1', test_mode=True)
        self.port = self.server.server_address[1]
        self.origin = f'http://127.0.0.1:{self.port}'
        self.server.RequestHandlerClass.operator_origin = self.origin
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        status, fields, data = response.status, dict(response.getheaders()), response.read().decode()
        connection.close()
        return status, fields, data

    def test_session_csrf_and_real_three_action_routes(self):
        status, _, _ = self.request('GET', '/api/clients')
        self.assertEqual(status, 401)
        status, headers, html = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('data-runtime="real_canary"', html)
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        status, _, body = self.request('GET', '/api/clients', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['clients'][0]['id'], PEER_ID)
        path = f'/api/clients/{PEER_ID}/disable'
        data = json.dumps({'idempotencyKey': 'disable-test-01', 'reason': 'operator_requested'})
        basic = {'Cookie': cookie, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', path, data, basic)[0], 403)
        with_origin = dict(basic, Origin=self.origin)
        self.assertEqual(self.request('POST', path, data, with_origin)[0], 403)
        trusted = dict(with_origin, **{'X-CSRF-Token': csrf})
        self.assertEqual(self.request('POST', path, data, dict(trusted, Origin='https://attacker.invalid'))[0], 403)
        status, _, body = self.request('POST', path, data, trusted)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['client']['status'], 'DISABLED')
        status, _, body = self.request('POST', f'/api/clients/{PEER_ID}/enable', json.dumps({'idempotencyKey': 'enable-test-01'}), trusted)
        self.assertEqual(status, 200)
        self.assertNotEqual(json.loads(body)['client']['status'], 'DISABLED')
        status, _, body = self.request('POST', f'/api/clients/{PEER_ID}/delete', json.dumps({'idempotencyKey': 'delete-test-01', 'confirmation': True}), trusted)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['deleted'])
        self.assertEqual(json.loads(self.request('GET', '/api/clients', headers={'Cookie': cookie})[2])['clients'], [])

    def test_bad_methods_content_and_payload_fail_without_mutation(self):
        _, headers, html = self.request('GET', '/')
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        trusted = {'Cookie': cookie, 'Origin': self.origin, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}
        path = f'/api/clients/{PEER_ID}/disable'
        self.assertEqual(self.request('POST', path, '{}', trusted)[0], 400)
        self.assertEqual(self.request('POST', path, '{', trusted)[0], 400)
        self.assertEqual(self.request('POST', path, '{}', dict(trusted, **{'Content-Type': 'text/plain'}))[0], 415)
        self.assertEqual(self.request('POST', f'/api/clients/{PEER_ID}/update', '{}', trusted)[0], 404)
        self.assertEqual(self.request('GET', f'/api/clients/{PEER_ID}/disable', headers={'Cookie': cookie})[0], 404)
        self.assertEqual(json.loads(self.request('GET', '/api/clients', headers={'Cookie': cookie})[2])['clients'][0]['status'], 'NEVER')

    def test_configuration_requires_session_and_is_not_cached(self):
        path = f'/api/clients/{PEER_ID}/config'
        self.assertEqual(self.request('GET', path)[0], 401)
        _, headers, _ = self.request('GET', '/')
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        config = '[Interface]\nPrivateKey = SYNTHETIC-ONLY\n'
        self.server.RequestHandlerClass.lifecycle_service.adapter.get_configuration = lambda _id: {
            'schema_version': 1, 'client': RECORD, 'configText': config,
            'qrDataUri': 'data:image/png;base64,c3ludGhldGlj', 'revision': 'a' * 64}
        status, headers, body = self.request('GET', path, headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(json.loads(body)['configText'], config)
        self.assertEqual(json.loads(body)['revision'], 'a' * 64)
        self.assertEqual(self.request('GET', path + '?copy=1', headers={'Cookie': cookie})[0], 404)

    def test_saved_config_update_requires_csrf_and_returns_readback(self):
        path = f'/api/clients/{PEER_ID}/config'
        _, headers, html = self.request('GET', '/')
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        adapter = self.server.RequestHandlerClass.lifecycle_service.adapter
        stored = {'mtu': 1420, 'revision': 'a' * 64}
        adapter.get_configuration = lambda _id: {
            'schema_version': 1, 'client': RECORD, 'configText': f'MTU = {stored["mtu"]}',
            'qrDataUri': 'data:image/png;base64,c3ludGhldGlj', 'revision': stored['revision']}
        def update(_id, expected, settings):
            self.assertEqual(expected, 'a' * 64)
            stored.update(mtu=settings['mtu'], revision='b' * 64)
            return adapter.get_configuration(_id)
        adapter.update_configuration = update
        payload = json.dumps({'dns_server': '127.0.0.1', 'allowed_ips': '0.0.0.0/0', 'mtu': 1280,
                              'keepalive': 25, 'expectedRevision': 'a' * 64, 'idempotencyKey': 'config-edit-001'})
        basic = {'Cookie': cookie, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', path, payload, basic)[0], 403)
        trusted = {**basic, 'Origin': self.origin, 'X-CSRF-Token': csrf}
        status, _, body = self.request('POST', path, payload, trusted)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['revision'], 'b' * 64)
        self.assertEqual(json.loads(body)['configText'], 'MTU = 1280')

    def test_profile_routes_keep_client_inventories_separate(self):
        handler = self.server.RequestHandlerClass
        handler.profile_services['awg2'] = LifecycleService(FakeAwgLifecycleAdapter([RECORD]))
        handler.profile_services['wg'] = LifecycleService(FakeAwgLifecycleAdapter([]))
        _, headers, html = self.request('GET', '/')
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        for profile in ('awg2', 'wg'):
            path = f'/api/profiles/{profile}/clients'
            self.assertEqual(self.request('GET', path)[0], 401)
            self.assertEqual(len(json.loads(self.request('GET', path, headers={'Cookie': cookie})[2])['clients']), 1 if profile == 'awg2' else 0)
            self.assertEqual(self.request('GET', path + '?copy=1', headers={'Cookie': cookie})[0], 404)
        self.assertEqual(len(json.loads(self.request('GET', '/api/profiles/awg3/clients', headers={'Cookie': cookie})[2])['clients']), 1)
        trusted = {'Cookie': cookie, 'Origin': self.origin, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}
        payload = json.dumps({'idempotencyKey': 'awg2-test-0001', 'reason': 'operator_requested'})
        status, _, _ = self.request('POST', f'/api/profiles/awg2/clients/{PEER_ID}/disable', payload, trusted)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.request('GET', '/api/profiles/awg2/clients', headers={'Cookie': cookie})[2])['clients'][0]['status'], 'DISABLED')
        self.assertEqual(json.loads(self.request('GET', '/api/profiles/awg3/clients', headers={'Cookie': cookie})[2])['clients'][0]['status'], 'NEVER')
        self.assertEqual(json.loads(self.request('GET', '/api/profiles/wg/clients', headers={'Cookie': cookie})[2])['clients'], [])

    def test_server_settings_requires_session(self):
        path = '/api/profiles/awg3/server'
        self.assertEqual(self.request('GET', path)[0], 401)
        _, headers, _ = self.request('GET', '/')
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        self.server.RequestHandlerClass.lifecycle_service.adapter.server_settings = lambda: {
            'schema_version': 1, 'profile': 'awg3', 'interface': 'awg-canary0',
            'endpoint': '127.0.0.1', 'address': '127.0.0.2/24', 'listenPort': 47192,
            'state': 'ACTIVE', 'clientCount': 1}
        status, fields, body = self.request('GET', path, headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertEqual(fields['Cache-Control'], 'no-store')
        self.assertEqual(json.loads(body)['listenPort'], 47192)

    def test_server_endpoint_update_requires_csrf_and_revision(self):
        path = '/api/profiles/awg3/server'
        _, headers, html = self.request('GET', '/')
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        endpoint = {'value': 'old.example.org', 'revision': 'a' * 64}
        adapter = self.server.RequestHandlerClass.lifecycle_service.adapter
        adapter.server_settings = lambda: {
            'schema_version': 1, 'profile': 'awg3', 'interface': 'awg-canary0',
            'endpoint': endpoint['value'], 'address': '127.0.0.2/24', 'listenPort': 47192,
            'state': 'ACTIVE', 'clientCount': 1, 'revision': endpoint['revision']}
        def update(expected, host):
            self.assertEqual(expected, 'a' * 64)
            endpoint.update(value=host, revision='b' * 64)
            return adapter.server_settings()
        adapter.update_server_endpoint = update
        payload = json.dumps({'expectedRevision': 'a' * 64, 'endpoint': 'new.example.org',
                              'idempotencyKey': 'endpoint-test-0001'})
        basic = {'Cookie': cookie, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', path, payload, basic)[0], 403)
        trusted = {**basic, 'Origin': self.origin, 'X-CSRF-Token': csrf}
        status, fields, body = self.request('POST', path, payload, trusted)
        self.assertEqual(status, 200)
        self.assertEqual(fields['Cache-Control'], 'no-store')
        self.assertEqual(json.loads(body)['endpoint'], 'new.example.org')
        self.assertEqual(self.request('POST', path, payload, trusted)[0], 409)

    def test_server_port_update_requires_csrf_and_revision(self):
        path = '/api/profiles/awg3/server/port'
        _, headers, html = self.request('GET', '/')
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        state = {'port': 47192, 'revision': 'a' * 64}
        adapter = self.server.RequestHandlerClass.lifecycle_service.adapter
        adapter.server_settings = lambda: {
            'schema_version': 1, 'profile': 'awg3', 'interface': 'awg-canary0',
            'endpoint': 'old.example.org', 'address': '127.0.0.2/24', 'listenPort': state['port'],
            'state': 'ACTIVE', 'clientCount': 1, 'revision': state['revision']}
        def update(expected, port):
            self.assertEqual(expected, 'a' * 64)
            state.update(port=port, revision='b' * 64)
            return adapter.server_settings()
        adapter.update_server_port = update
        payload = json.dumps({'expectedRevision': 'a' * 64, 'listenPort': 48192,
                              'idempotencyKey': 'port-test-0001'})
        basic = {'Cookie': cookie, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', path, payload, basic)[0], 403)
        trusted = {**basic, 'Origin': self.origin, 'X-CSRF-Token': csrf}
        status, fields, body = self.request('POST', path, payload, trusted)
        self.assertEqual(status, 200)
        self.assertEqual(fields['Cache-Control'], 'no-store')
        self.assertEqual(json.loads(body)['listenPort'], 48192)
        self.assertEqual(self.request('POST', path, payload, trusted)[0], 409)

    def test_network_update_is_scoped_validated_and_requires_csrf(self):
        path = '/api/profiles/wg/server/network'
        _, headers, html = self.request('GET', '/')
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        state = {'address': '127.33.0.1/24', 'revision': 'a' * 64}
        adapter = FakeAwgLifecycleAdapter([])
        adapter._profile = 'wg'
        adapter.server_settings = lambda: {
            'schema_version': 1, 'profile': 'wg', 'interface': 'awg-cita-wg',
            'endpoint': 'example.org', 'address': state['address'], 'listenPort': 47194,
            'state': 'ACTIVE', 'clientCount': 0, 'revision': state['revision']}
        def update(expected, kind, target):
            self.assertEqual((expected, kind), ('a' * 64, 'address'))
            state.update(address=target, revision='b' * 64)
            return adapter.server_settings()
        adapter.update_server_network = update
        self.server.RequestHandlerClass.profile_services['wg'] = LifecycleService(adapter)
        payload = json.dumps({'expectedRevision': 'a' * 64, 'address': '127.43.0.1/24',
                              'idempotencyKey': 'network-test-0001'})
        basic = {'Cookie': cookie, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', path, payload, basic)[0], 403)
        trusted = {**basic, 'Origin': self.origin, 'X-CSRF-Token': csrf}
        self.assertEqual(self.request('POST', '/api/profiles/awg3/server/network', payload, trusted)[0], 404)
        self.assertEqual(self.request('POST', path, payload.replace('"address"', '"obfuscation"'), trusted)[0], 400)
        status, _, body = self.request('POST', path, payload, trusted)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['address'], '127.43.0.1/24')
        self.assertEqual(self.request('POST', path, payload, trusted)[0], 409)

    def test_template_update_requires_csrf_and_is_profile_scoped(self):
        _, headers, html = self.request('GET', '/')
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        template = {'dns_server': '127.0.0.1', 'allowed_ips': '0.0.0.0/0', 'mtu': 1420, 'keepalive': 25}
        reply = json.dumps({'schema_version': 1, 'profile': 'wg', 'template': template})
        path = '/api/profiles/wg/template'
        with patch.object(AwgReader, '_run', return_value=(reply, '')) as run:
            self.assertEqual(self.request('GET', path)[0], 401)
            self.assertEqual(self.request('GET', path, headers={'Cookie': cookie})[0], 200)
            payload = json.dumps({**template, 'idempotencyKey': 'template-wg-0001'})
            basic = {'Cookie': cookie, 'Content-Type': 'application/json'}
            self.assertEqual(self.request('POST', path, payload, basic)[0], 403)
            trusted = {**basic, 'Origin': self.origin, 'X-CSRF-Token': csrf}
            self.assertEqual(self.request('POST', path, payload, trusted)[0], 200)
            self.assertEqual(self.request('POST', path + '?x=1', payload, trusted)[0], 404)
            self.assertEqual(run.call_args.args[0][-2:], ('wg', 'update'))

    def test_identity_and_action_audit_fail_closed(self):
        class ActionAudit:
            def __init__(self):
                self.events = []
                self.fail_phase = None

            def record_action(self, **event):
                if event['phase'] == self.fail_phase:
                    raise RuntimeError('disk failure')
                self.events.append(event)

        audit = ActionAudit()
        handler = self.server.RequestHandlerClass
        handler.operator_id = 'operator-1'
        handler.require_operator_header = True
        handler.action_audit_log = audit
        self.assertEqual(self.request('GET', '/')[0], 401)
        status, headers, html = self.request('GET', '/', headers={'X-AWG-Operator': 'operator-1'})
        self.assertEqual(status, 200)
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        payload = json.dumps({'idempotencyKey': 'audit-test-01', 'reason': 'operator_requested'})
        trusted = {'X-AWG-Operator': 'operator-1', 'Cookie': cookie, 'Origin': self.origin,
                   'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}
        path = f'/api/clients/{PEER_ID}/disable'
        self.assertEqual(self.request('POST', path, payload, dict(trusted, **{'X-AWG-Operator': 'forged'}))[0], 401)
        audit.fail_phase = 'INTENT'
        self.assertEqual(self.request('POST', path, payload, trusted)[0], 503)
        self.assertEqual(json.loads(self.request('GET', '/api/clients', headers={'Cookie': cookie, 'X-AWG-Operator': 'operator-1'})[2])['clients'][0]['status'], 'NEVER')
        audit.fail_phase = None
        self.assertEqual(self.request('POST', path, payload, trusted)[0], 200)
        self.assertEqual([event['phase'] for event in audit.events], ['INTENT', 'RESULT'])
        self.assertEqual(audit.events[0]['actor'], 'operator-1')
        self.assertEqual(audit.events[0]['correlation_id'], audit.events[1]['correlation_id'])
        self.assertNotIn('audit-test-01', str(audit.events))

    def test_action_server_refuses_tcp_without_explicit_test_mode(self):
        reader = AwgReader(binary='/unused', interface='awg-canary0', runner=lambda *_: ('', ''))
        with self.assertRaises(ValueError):
            create_server(reader, '127.0.0.1', 0,
                          lifecycle_service=LifecycleService(FakeAwgLifecycleAdapter([RECORD])),
                          operator_origin='http://127.0.0.1')

    def test_action_server_refuses_nonfixed_unix_path_in_production(self):
        reader = AwgReader(binary='/unused', interface='awg-canary0', runner=lambda *_: ('', ''))
        with self.assertRaises(ValueError):
            create_server(reader, lifecycle_service=LifecycleService(FakeAwgLifecycleAdapter([RECORD])),
                          operator_origin='http://127.0.0.1', unix_socket_path='/tmp/unsafe.sock')

    def test_read_only_tcp_never_issues_session_or_accepts_action(self):
        reader = AwgReader(binary='/unused', interface='awg-canary0', runner=lambda *_: ('', ''))
        server = create_server(reader, '127.0.0.1', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
            connection.request('GET', '/')
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIsNone(response.getheader('Set-Cookie'))
            self.assertNotIn('data-runtime="real_canary"', response.read().decode())
            connection.request('POST', f'/api/clients/{PEER_ID}/disable', body='{}',
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.status, 405)
            response.read()
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


@unittest.skipUnless(hasattr(socket, 'AF_UNIX'), 'Unix sockets unavailable')
class CanaryUnixIngressTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='cita-', dir=os.environ.get('AWG_UNIX_TEST_DIR', str(Path(__file__).resolve().parents[1])))
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / 'backend.sock')
        self.reader = AwgReader(binary='/unused', interface='awg-canary0', runner=lambda *_: ('', ''))
        self.service = LifecycleService(FakeAwgLifecycleAdapter([RECORD]))

    def start(self):
        self.server = create_server(self.reader, lifecycle_service=self.service,
                                    operator_origin='http://127.0.0.1',
                                    test_mode=True, unix_socket_path=self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        if not hasattr(self, 'server'):
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        del self.server

    def request(self, method, path, body=None, headers=None):
        class UnixHTTPConnection(HTTPConnection):
            def connect(connection):
                connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.sock.settimeout(3)
                connection.sock.connect(self.path)

        connection = UnixHTTPConnection('127.0.0.1', timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read().decode()
        connection.close()
        return result

    def test_private_socket_serves_session_and_action(self):
        self.start()
        status, headers, html = self.request('GET', '/')
        self.assertEqual(status, 200)
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        payload = json.dumps({'idempotencyKey': 'disable-uds-01', 'reason': 'operator_requested'})
        status, _, _ = self.request('POST', f'/api/clients/{PEER_ID}/disable', payload,
                                    {'Cookie': cookie, 'Origin': 'http://127.0.0.1',
                                     'X-CSRF-Token': csrf, 'Content-Type': 'application/json'})
        self.assertEqual(status, 200)

    @unittest.skipUnless(os.name == 'posix', 'POSIX metadata semantics required')
    def test_socket_owner_mode_and_close_cleanup(self):
        self.start()
        metadata = os.lstat(self.path)
        self.assertTrue(stat.S_ISSOCK(metadata.st_mode))
        self.assertEqual(metadata.st_uid, os.geteuid())
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
        self.stop()
        self.assertFalse(os.path.lexists(self.path))

    def test_existing_socket_path_and_symlink_are_never_removed(self):
        for kind in ('file', 'symlink'):
            with self.subTest(kind=kind):
                target = Path(self.path)
                target.write_text('keep') if kind == 'file' else target.symlink_to(Path(self.directory.name) / 'missing')
                with self.assertRaises((ValueError, OSError)):
                    create_server(self.reader, lifecycle_service=self.service,
                                  operator_origin='http://127.0.0.1',
                                  test_mode=True, unix_socket_path=self.path)
                self.assertTrue(target.is_symlink() if kind == 'symlink' else target.read_text() == 'keep')
                target.unlink()

    def test_second_server_cannot_replace_live_socket(self):
        self.start()
        with self.assertRaises((ValueError, OSError)):
            create_server(self.reader, lifecycle_service=self.service,
                          operator_origin='http://127.0.0.1',
                          test_mode=True, unix_socket_path=self.path)
        self.assertEqual(self.request('GET', '/')[0], 200)

    @unittest.skipUnless(os.name == 'posix', 'POSIX metadata semantics required')
    def test_unsafe_parent_refuses_bind(self):
        os.chmod(self.directory.name, 0o755)
        with self.assertRaises(ValueError):
            create_server(self.reader, lifecycle_service=self.service,
                          operator_origin='http://127.0.0.1',
                          test_mode=True, unix_socket_path=self.path)
        self.assertFalse(os.path.lexists(self.path))

    @unittest.skipUnless(os.name == 'posix', 'POSIX metadata semantics required')
    def test_failed_socket_chmod_cleans_only_new_socket(self):
        with patch('awg_cita.app.os.chmod', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                create_server(self.reader, lifecycle_service=self.service,
                              operator_origin='http://127.0.0.1',
                              test_mode=True, unix_socket_path=self.path)
        self.assertFalse(os.path.lexists(self.path))


if __name__ == '__main__':
    unittest.main()
