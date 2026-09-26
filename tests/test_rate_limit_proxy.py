"""Integration tests for the existing public AWG relay, without AWG mutations."""
import json
import dis
import os
import re
import runpy
import socket
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingMixIn
try:
    from socketserver import UnixStreamServer
except ImportError:
    UnixStreamServer = object  # type: ignore[assignment,misc]  # Linux-only tests are skipped on Windows.
from pathlib import Path
from unittest.mock import patch

from awg_cita.app import AwgReader, create_server
from awg_cita.lifecycle import FakeAwgLifecycleAdapter, LifecycleService

RELAY = Path(__file__).resolve().parents[1] / 'scripts' / 'rate_limit_proxy.py'
HOST = 'panel.example'
COOKIE = 'awg_cita_session=synthetic-session'

class TimeoutBoundaryTests(unittest.TestCase):
    def test_network_settings_route_is_allowed_only_for_isolated_profiles(self):
        allowed = runpy.run_path(str(RELAY))['post_path_allowed']
        self.assertTrue(allowed('/api/profiles/awg2/server/network'))
        self.assertTrue(allowed('/api/profiles/wg/server/network'))
        self.assertFalse(allowed('/api/profiles/awg3/server/network'))
        self.assertFalse(allowed('/api/profiles/wg/server/network/extra'))
        self.assertTrue(allowed('/api/profiles/awg3/server/port'))

    def test_client_list_relay_deadline_exceeds_helper_and_lock(self):
        relay = runpy.run_path(str(RELAY))
        self.assertGreaterEqual(relay['CLIENT_READ_TIMEOUT'], 30)
        self.assertIn('CLIENT_READ_TIMEOUT', {item.argval for item in dis.get_instructions(relay['Handler'].do_GET)})

    def test_action_relay_deadline_exceeds_complete_helper_deadline(self):
        from awg_cita.real_awg import ACTION_HELPER_TIMEOUT
        relay = runpy.run_path(str(RELAY))
        # Lock + inventory + key commands + runtime read + restart + readback + rollback.
        worst_case_seconds = 5 + 5 + 30 + 5 + 70 + 5 + 70
        self.assertGreaterEqual(ACTION_HELPER_TIMEOUT, worst_case_seconds + 60)
        self.assertGreaterEqual(relay['ACTION_BACKEND_TIMEOUT'], ACTION_HELPER_TIMEOUT + 30)
        self.assertIn('ACTION_BACKEND_TIMEOUT', {item.argval for item in dis.get_instructions(relay['Handler'].do_POST)})


class UnixHTTPConnection(HTTPConnection):
    def __init__(self, path, timeout=3):
        super().__init__('localhost', timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class UnixHTTPServer(ThreadingMixIn, UnixStreamServer):
    daemon_threads = True


@unittest.skipUnless(os.name == 'posix' and hasattr(socket, 'AF_UNIX'), 'Unix sockets require POSIX Python')
class UnixIngressContractTests(unittest.TestCase):
    def test_relay_has_no_tcp_listener_and_uses_unix_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            backend_path = str(Path(directory) / 'backend.sock')
            relay_path = str(Path(directory) / 'relay.sock')
            backend = UnixHTTPServer(backend_path, Backend)
            backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
            backend_thread.start()
            try:
                module = runpy.run_path(str(RELAY))
                module['Handler'].do_GET.__globals__['BACKEND_SOCKET'] = backend_path
                relay = module['RelayServer'](relay_path, module['Handler'],
                                              owner_uid=os.geteuid(), group_gid=os.getegid())
                self.assertEqual(os.stat(relay_path).st_mode & 0o777, 0o660)
                self.assertEqual(os.stat(relay_path).st_gid, os.getegid())
                relay_thread = threading.Thread(target=relay.serve_forever, daemon=True)
                relay_thread.start()
                try:
                    conn = UnixHTTPConnection(relay_path)
                    conn.request('GET', '/', headers={'Host': HOST, 'X-AWG-Operator': 'test-operator'})
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                    conn.close()
                    self.assertEqual(Backend.seen[-1][2], HOST)
                    with self.assertRaises((ConnectionRefusedError, OSError)):
                        socket.create_connection(('127.0.0.1', 8790), timeout=0.2)
                finally:
                    relay.shutdown()
                    relay.server_close()
                    relay_thread.join(timeout=3)
            finally:
                backend.shutdown()
                backend.server_close()
                backend_thread.join(timeout=3)

    def test_socket_replacement_during_permission_setup_is_not_unlinked(self):
        with tempfile.TemporaryDirectory() as directory:
            relay_path = str(Path(directory) / 'relay.sock')
            target = str(Path(directory) / 'safe-target')
            Path(target).write_text('untouched')
            module = runpy.run_path(str(RELAY))
            def replace_socket(path, uid, gid):
                os.unlink(path)
                os.symlink(target, path)
                raise PermissionError('socket path changed')

            with patch('os.chown', side_effect=replace_socket):
                with self.assertRaises((PermissionError, OSError)):
                    module['RelayServer'](relay_path, module['Handler'],
                                          owner_uid=os.geteuid(), group_gid=os.getegid())
            self.assertTrue(os.path.islink(relay_path))
            self.assertEqual(Path(target).read_text(), 'untouched')


class Backend(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    seen = []
    seen_operators = []
    posts = []

    def log_message(self, *args):
        pass

    def respond(self, status, payload, cookie=False):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        if cookie:
            self.send_header('Set-Cookie', COOKIE + '; HttpOnly; SameSite=Strict; Secure; Path=/')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.seen.append((self.path, self.headers.get('Cookie'), self.headers.get('Host')))
        self.seen_operators.append(self.headers.get_all('X-AWG-Operator'))
        if self.path == '/':
            self.respond(200, {'page': True}, cookie=True)
        elif self.path == '/api/clients':
            self.respond(200 if self.headers.get('Cookie') == COOKIE else 401,
                         {'clients': []} if self.headers.get('Cookie') == COOKIE else {'error_code': 'unauthorized'})
        else:
            self.respond(404, {'error_code': 'not_found'})

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length)
        self.posts.append((self.path, dict(self.headers), body))
        expected = (self.path == '/api/clients/peer-0123456789abcdef/disable' and
                    self.headers.get('Cookie') == COOKIE and
                    self.headers.get('Origin') == 'https://' + HOST + ':8444' and
                    self.headers.get('X-CSRF-Token') == 'synthetic-csrf' and
                    self.headers.get('Sec-Fetch-Site') == 'same-origin' and
                    self.headers.get('Content-Type') == 'application/json' and
                    json.loads(body) == {'idempotencyKey': 'test-01', 'reason': 'operator_requested'})
        self.respond(200 if expected else 403, {'schema_version': 1} if expected else {'error_code': 'forbidden'})


@unittest.skipUnless(os.name == 'posix' and hasattr(socket, 'AF_UNIX'), 'Unix sockets require POSIX Python')
class RateLimitRelayTests(unittest.TestCase):
    def setUp(self):
        Backend.seen = []
        Backend.seen_operators = []
        Backend.posts = []
        self.sockets = tempfile.TemporaryDirectory()
        self.backend_path = str(Path(self.sockets.name) / 'backend.sock')
        self.relay_path = str(Path(self.sockets.name) / 'relay.sock')
        self.backend = UnixHTTPServer(self.backend_path, Backend)
        self.backend_thread = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.backend_thread.start()
        module = runpy.run_path(str(RELAY))
        relay_handler = module['Handler']
        relay_handler.do_GET.__globals__['BACKEND_SOCKET'] = self.backend_path
        relay_handler.do_GET.__globals__['tokens'] = 6.0
        relay_handler.do_GET.__globals__['action_tokens'] = 6.0
        relay_handler.do_GET.__globals__['client_tokens'] = 6.0
        self.relay = module['RelayServer'](self.relay_path, relay_handler,
                                           owner_uid=os.geteuid(), group_gid=os.getegid())
        self.relay_thread = threading.Thread(target=self.relay.serve_forever, daemon=True)
        self.relay_thread.start()

    def tearDown(self):
        for server, thread in ((self.relay, self.relay_thread), (self.backend, self.backend_thread)):
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        self.sockets.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = UnixHTTPConnection(self.relay_path)
        conn.request(method, path, body=body, headers={'Host': HOST, 'X-AWG-Operator': 'test-operator', **(headers or {})})
        response = conn.getresponse()
        status, fields, data = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return status, fields, data

    def raw_status(self, method, path, body=b'', headers=None):
        fields = {'Host': HOST, 'X-AWG-Operator': 'test-operator', 'Content-Length': str(len(body)),
                  **(headers or {})}
        request = (f'{method} {path} HTTP/1.1\r\n' +
                   ''.join(f'{key}: {value}\r\n' for key, value in fields.items()) +
                   '\r\n').encode() + body
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(self.relay_path)
            client.sendall(request)
            return int(client.recv(1024).split(b'\r\n', 1)[0].split()[1])

    def test_public_get_carries_only_application_session_to_backend(self):
        status, headers, _ = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Set-Cookie'), COOKIE + '; HttpOnly; SameSite=Strict; Secure; Path=/')
        status, _, body = self.request('GET', '/api/clients', headers={'Cookie': 'unrelated=private; ' + COOKIE})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'clients': []})
        self.assertEqual(Backend.seen[-1], ('/api/clients', COOKIE, HOST))
        self.assertEqual(Backend.seen_operators[-1], ['test-operator'])

    def test_missing_or_forged_identity_never_reaches_backend(self):
        for actor in ('wrong-operator', ''):
            with self.subTest(actor=actor):
                self.assertEqual(self.request('GET', '/', headers={'X-AWG-Operator': actor})[0], 401)
        raw = (f'GET / HTTP/1.1\r\nHost: {HOST}\r\n'
               'X-AWG-Operator: test-operator\r\nX-AWG-Operator: test-operator\r\n\r\n').encode()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(self.relay_path)
            client.sendall(raw)
            self.assertIn(b' 401 ', client.recv(1024).split(b'\r\n', 1)[0])
        self.assertEqual(Backend.seen, [])

    def test_public_canary_post_preserves_session_origin_csrf_and_body(self):
        body = json.dumps({'idempotencyKey': 'test-01', 'reason': 'operator_requested'}).encode()
        status, _, response = self.request(
            'POST', '/api/clients/peer-0123456789abcdef/disable', body,
            {'Cookie': 'unrelated=private; ' + COOKIE, 'Origin': 'https://' + HOST + ':8444',
             'X-CSRF-Token': 'synthetic-csrf', 'Sec-Fetch-Site': 'same-origin',
             'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response), {'schema_version': 1})
        self.assertEqual(len(Backend.posts), 1)
        self.assertNotIn('unrelated', Backend.posts[0][1]['Cookie'])

    def test_network_settings_post_reaches_backend_only_for_awg2_and_wg(self):
        headers = {'Cookie': COOKIE, 'Origin': 'https://' + HOST + ':8444',
                   'X-CSRF-Token': 'synthetic-csrf', 'Content-Type': 'application/json'}
        for profile in ('awg2', 'wg'):
            path = f'/api/profiles/{profile}/server/network'
            self.assertEqual(self.raw_status('POST', path, b'{}', headers), 403)
            self.assertEqual(Backend.posts[-1][0], path)
        forwarded = len(Backend.posts)
        self.assertEqual(self.raw_status('POST', '/api/profiles/awg3/server/network', b'{}', headers), 404)
        self.assertEqual(len(Backend.posts), forwarded)

    def test_untrusted_posts_never_reach_backend(self):
        path = '/api/clients/peer-0123456789abcdef/disable'
        body = b'{}'
        trusted = {'Cookie': COOKIE, 'Origin': 'https://' + HOST + ':8444',
                   'X-CSRF-Token': 'synthetic-csrf', 'Sec-Fetch-Site': 'same-origin',
                   'Content-Type': 'application/json'}
        cases = (
            ('/api/admin', trusted, 404),
            (path + '?other=1', trusted, 404),
            (path, dict(trusted, Host='attacker.invalid'), 421),
            (path, dict(trusted, Origin='https://attacker.invalid'), 403),
            (path, {key: value for key, value in trusted.items() if key != 'X-CSRF-Token'}, 403),
            (path, dict(trusted, **{'Sec-Fetch-Site': 'cross-site'}), 403),
            (path, dict(trusted, **{'Content-Type': 'text/plain'}), 415),
            (path, {key: value for key, value in trusted.items() if key != 'Cookie'}, 401),
        )
        for route, headers, expected in cases:
            with self.subTest(route=route, expected=expected, headers=tuple(headers)):
                self.assertEqual(self.raw_status('POST', route, body, headers), expected)
        self.assertEqual(Backend.posts, [])
        self.assertEqual(self.raw_status('POST', path, b'x' * 2049, trusted), 400)
        self.assertEqual(Backend.posts, [])

    def test_status_rate_limit_remains_in_force(self):
        statuses = [self.request('GET', '/api/status')[0] for _ in range(7)]
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(statuses[:6], [404] * 6)

    def test_action_rate_limit_is_separate_from_status_budget(self):
        path = '/api/clients/peer-0123456789abcdef/disable'
        headers = {'Cookie': COOKIE, 'Origin': 'https://' + HOST + ':8444',
                   'X-CSRF-Token': 'synthetic-csrf', 'Content-Type': 'application/json'}
        body = json.dumps({'idempotencyKey': 'test-01', 'reason': 'operator_requested'}).encode()
        statuses = [self.raw_status('POST', path, body, headers) for _ in range(7)]
        self.assertEqual(statuses[:6], [200] * 6)
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(len(Backend.posts), 6)
        self.assertEqual(self.request('GET', '/api/status')[0], 404)

    def test_client_read_has_rate_and_concurrency_bound(self):
        statuses = [self.request('GET', '/api/clients', headers={'Cookie': COOKIE})[0] for _ in range(7)]
        self.assertEqual(statuses[:6], [200] * 6)
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(len(Backend.seen), 6)
        slots = self.relay.RequestHandlerClass.do_GET.__globals__['action_slots']
        self.relay.RequestHandlerClass.do_GET.__globals__['client_tokens'] = 6.0
        self.assertTrue(all(slots.acquire(blocking=False) for _ in range(3)))
        try:
            self.assertEqual(self.request('GET', '/api/clients', headers={'Cookie': COOKIE})[0], 429)
            self.assertEqual(len(Backend.seen), 6)
        finally:
            for _ in range(3):
                slots.release()

    def test_empty_transfer_encoding_and_oversized_length_are_rejected(self):
        path = '/api/clients/peer-0123456789abcdef/disable'
        headers = {'Cookie': COOKIE, 'Origin': 'https://' + HOST + ':8444',
                   'X-CSRF-Token': 'synthetic-csrf', 'Content-Type': 'application/json'}
        self.assertEqual(self.raw_status('POST', path, b'{}', dict(headers, **{'Transfer-Encoding': ''})), 400)
        self.assertEqual(self.raw_status('POST', path, b'{}', dict(headers, **{'Content-Length': '0' * 5000})), 400)
        self.assertEqual(Backend.posts, [])

    def test_action_concurrency_slots_refuse_before_forwarding(self):
        slots = self.relay.RequestHandlerClass.do_GET.__globals__['action_slots']
        self.assertTrue(all(slots.acquire(blocking=False) for _ in range(3)))
        try:
            path = '/api/clients/peer-0123456789abcdef/disable'
            headers = {'Cookie': COOKIE, 'Origin': 'https://' + HOST + ':8444',
                       'X-CSRF-Token': 'synthetic-csrf', 'Content-Type': 'application/json'}
            self.assertEqual(self.raw_status('POST', path, b'{}', headers), 429)
            self.assertEqual(Backend.posts, [])
        finally:
            for _ in range(3):
                slots.release()

    def test_duplicate_framing_never_reaches_backend(self):
        for extra in ('Content-Length: 2', 'Transfer-Encoding:'):
            with self.subTest(extra=extra):
                request = (
                    'POST /api/clients/peer-0123456789abcdef/disable HTTP/1.1\r\n'
                    f'Host: {HOST}\r\nOrigin: https://{HOST}:8444\r\n'
                    'X-AWG-Operator: test-operator\r\n'
                    'X-CSRF-Token: synthetic-csrf\r\nContent-Type: application/json\r\n'
                    f'Cookie: {COOKIE}\r\nContent-Length: 2\r\n{extra}\r\n\r\n{{}}'
                ).encode()
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(3)
                    client.connect(self.relay_path)
                    client.sendall(request)
                    self.assertIn(b' 400 ', client.recv(1024).split(b'\r\n', 1)[0])
        self.assertEqual(Backend.posts, [])

    def test_truncated_post_body_never_reaches_backend(self):
        request = (
            f'POST /api/clients/peer-0123456789abcdef/disable HTTP/1.1\r\n'
            f'Host: {HOST}\r\n'
            'X-AWG-Operator: test-operator\r\n'
            f'Origin: https://{HOST}:8444\r\n'
            'X-CSRF-Token: synthetic-csrf\r\n'
            'Sec-Fetch-Site: same-origin\r\n'
            'Content-Type: application/json\r\n'
            f'Cookie: {COOKIE}\r\n'
            'Content-Length: 48\r\n\r\n{}'
        ).encode()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(self.relay_path)
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            status_line = client.recv(1024).split(b'\r\n', 1)[0]
        self.assertIn(b' 400 ', status_line)
        self.assertEqual(Backend.posts, [])

    def test_public_relay_reaches_real_session_and_csrf_contract(self):
        self.backend.shutdown()
        self.backend.server_close()
        self.backend_thread.join(timeout=3)
        os.unlink(self.backend_path)
        record = {
            'id': 'peer-0123456789abcdef', 'name': 'Test Peer', 'status': 'NEVER',
            'lastHandshakeAt': None, 'lastSeenAt': None, 'createdAt': None,
            'expiration': '', 'rxBytes': 0, 'txBytes': 0, 'notes': '', 'tags': [], 'warning': ''
        }
        self.backend = create_server(
            AwgReader(binary='/unused', interface='awg-canary0', runner=lambda *_: ('', '')),
            '127.0.0.1', 0, allowed_hosts=frozenset({HOST}), test_mode=True,
            lifecycle_service=LifecycleService(FakeAwgLifecycleAdapter([record])),
            operator_origin='https://' + HOST + ':8444', unix_socket_path=self.backend_path)
        self.backend_thread = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.backend_thread.start()

        status, headers, html = self.request('GET', '/')
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        csrf = re.search(rb'<meta name="csrf-token" content="([^"]+)">', html).group(1).decode()
        self.assertEqual(self.request('GET', '/api/clients', headers={'Cookie': cookie})[0], 200)
        path = '/api/clients/peer-0123456789abcdef/disable'
        body = json.dumps({'idempotencyKey': 'public-disable-01', 'reason': 'operator_requested'}).encode()
        trusted = {'Cookie': cookie, 'Origin': 'https://' + HOST + ':8444',
                   'X-CSRF-Token': csrf, 'Sec-Fetch-Site': 'same-origin', 'Content-Type': 'application/json'}
        for _ in range(3):
            self.assertEqual(self.request('POST', path, body, dict(trusted, **{'X-CSRF-Token': 'wrong'}))[0], 403)
        status, _, result = self.request('POST', path, body, trusted)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(result)['client']['status'], 'DISABLED')
        status, _, result = self.request('GET', '/api/clients', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(result)['clients'][0]['status'], 'DISABLED')


if __name__ == '__main__':
    unittest.main()
