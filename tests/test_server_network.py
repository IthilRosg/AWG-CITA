import base64
import unittest
from pathlib import Path
from unittest.mock import patch

from awg_cita.real_awg import PersistentCanaryConfig
from awg_cita.server_network import (apply_change, recover_pending, rewrite_client_address, rewrite_obfuscation,
                                     rewrite_server_address, validate_address_change,
                                     validate_obfuscation)


OLD = '127.32.0.1/24'
NEW = '127.42.0.1/24'
HOOKS = [
    f'PostUp = iptables -I FORWARD -s 127.32.0.0/24 -j ACCEPT\n',
    f'PostUp = iptables -I FORWARD -d 127.32.0.0/24 -j ACCEPT\n',
    f'PostUp = iptables -t nat -I POSTROUTING -s 127.32.0.0/24 -j MASQUERADE\n',
    f'PostDown = iptables -D FORWARD -s 127.32.0.0/24 -j ACCEPT\n',
    f'PostDown = iptables -D FORWARD -d 127.32.0.0/24 -j ACCEPT\n',
    f'PostDown = iptables -t nat -D POSTROUTING -s 127.32.0.0/24 -j MASQUERADE\n',
]
KEY1 = base64.b64encode(bytes(range(32))).decode()
KEY2 = base64.b64encode(bytes(range(32, 64))).decode()


def fixture() -> bytes:
    disabled = f'[Peer]\nPublicKey = {KEY2}\nAllowedIPs = 127.32.0.3/32\n'.encode()
    return (f'[Interface]\nAddress = {OLD}\n' + ''.join(HOOKS) +
            f'[Peer]\nPublicKey = {KEY1}\nAllowedIPs = 127.32.0.2/32\n' +
            '# AWG-CITA-DISABLED ' + base64.b64encode(disabled).decode() + '\n').encode()


class ServerNetworkTests(unittest.TestCase):
    def test_address_rewrite_maps_enabled_and_disabled_peers(self):
        result = rewrite_server_address(fixture(), OLD, NEW)
        parsed = PersistentCanaryConfig(result)
        self.assertIn(b'Address = 127.42.0.1/24\n', result)
        self.assertEqual(result.count(b'127.42.0.0/24'), 6)
        self.assertEqual(parsed.peers(), {KEY1: 'enabled', KEY2: 'disabled'})
        self.assertIn(b'AllowedIPs = 127.42.0.2/32\n', parsed._entries[KEY1][2])
        self.assertIn(b'AllowedIPs = 127.42.0.3/32\n', parsed._entries[KEY2][2])

    def test_client_address_rewrite_preserves_other_fields(self):
        old = '[Interface]\nPrivateKey = secret\nAddress = 127.32.0.2/32\nDNS = 127.0.0.1\n[Peer]\nEndpoint = host:47193\n'
        self.assertEqual(rewrite_client_address(old, OLD, NEW), old.replace('127.32.0.2/32', '127.42.0.2/32'))

    def test_rejects_prefix_or_host_offset_change_and_drift(self):
        for target in ('127.42.0.2/24', '127.42.0.1/25', '127.32.0.1/24', '::1/64'):
            with self.assertRaises(ValueError):
                validate_address_change(OLD, target)
        with self.assertRaises(ValueError):
            rewrite_server_address(fixture().replace(b'PostUp = ', b'PostUpX = ', 1), OLD, NEW)
        with self.assertRaises(ValueError):
            rewrite_client_address('[Interface]\nAddress = 127.99.0.2/32\n', OLD, NEW)

    def test_obfuscation_rewrite_requires_exact_old_values(self):
        old = {'S1': '20', 'S2': '24', 'S3': '0', 'S4': '0',
               'H1': '101', 'H2': '102', 'H3': '103', 'H4': '104'}
        new = {**old, 'H1': '201'}
        raw = ('[Interface]\n' + ''.join(f'{key} = {value}\n' for key, value in old.items())).encode()
        result = rewrite_obfuscation(raw, old, new)
        self.assertIn(b'H1 = 201\n', result)
        with self.assertRaises(ValueError):
            rewrite_obfuscation(raw.replace(b'H1 = 101', b'H1 = 102'), old, new)
        with self.assertRaises(ValueError):
            validate_obfuscation({**new, 'H4': '-1'})

    def test_address_transaction_stops_before_writes_and_restores_after_failure(self):
        import awg_cita.server_network as network
        old_client = '[Interface]\nAddress = 127.32.0.2/32\n[Peer]\nEndpoint = host:47193\n'
        old_client2 = old_client.replace('.2/32', '.3/32')
        old_metadata = b'{"endpoint_host":"host","dns_server":"127.0.0.1","interface_address":"127.32.0.1/24","listen_port":47193,"obfuscation":{}}\n'
        state = {'config': fixture(), 'metadata': old_metadata,
                 'peer-' + __import__('hashlib').sha256(base64.b64decode(KEY1)).hexdigest()[:16]: old_client.encode(),
                 'peer-' + __import__('hashlib').sha256(base64.b64decode(KEY2)).hexdigest()[:16]: old_client2.encode()}
        original = state.copy()
        events = []
        journal = {'files': None}
        fail = {'enabled': True}
        fail_verify = {'enabled': False}

        class Controller:
            def list_clients(self):
                return [{'id': key} for key in state if key.startswith('peer-')]

        class Ops:
            name = 'wg'
            interface = 'awg-cita-wg'
            profile = Path('/metadata')
            def settings(self):
                import json
                data = json.loads(state['metadata'])
                return data['endpoint_host'], data['dns_server'], data['interface_address'], data['listen_port'], data['obfuscation']
            def read_config(self): return state['config']
            def controller(self): return Controller()
            def load_config(self, name, _controller): return {'configText': state[name].decode()}
            def stop_runtime(self): events.append('stop')
            def start_runtime(self): events.append('start')
            def verify_runtime(self):
                events.append('verify')
                if fail_verify['enabled']:
                    fail_verify['enabled'] = False
                    raise ValueError('injected runtime verification failure')

        def replace(_ops, name, before, after):
            self.assertEqual(state[name], before)
            self.assertIn('stop', events)
            events.append('write:' + name)
            if name == 'metadata' and fail['enabled']:
                fail['enabled'] = False
                raise ValueError('injected metadata write failure')
            state[name] = after

        def write_journal(_profile, _kind, files):
            journal['files'] = files

        def finish(_profile): journal['files'] = None
        with (patch.object(network, 'read_root_settings', side_effect=lambda _path, _limit: state['metadata']),
              patch.object(network, '_read_file', side_effect=lambda _ops, name: state[name]),
              patch.object(network, '_replace_file', side_effect=replace),
              patch.object(network, '_write_journal', side_effect=write_journal),
              patch.object(network, '_parse_journal', side_effect=lambda _profile: journal['files']),
              patch.object(network, '_finish_journal', side_effect=finish),
              patch.object(network, 'preflight_route')):
            with self.assertRaisesRegex(ValueError, 'injected metadata'):
                apply_change(Ops(), network.revision(old_metadata), 'address', NEW)
            self.assertEqual(state, original)
            self.assertIsNone(journal['files'])
            self.assertEqual(events[:3], ['stop', 'write:config', 'write:metadata'])
            events.clear()
            fail_verify['enabled'] = True
            with self.assertRaisesRegex(ValueError, 'injected runtime'):
                apply_change(Ops(), network.revision(old_metadata), 'address', NEW)
            self.assertEqual(state, original)
            self.assertIsNone(journal['files'])
            self.assertEqual(events.count('stop'), 2)
            self.assertEqual(events.count('start'), 2)
            events.clear()
            apply_change(Ops(), network.revision(old_metadata), 'address', NEW)
            self.assertIn(b'Address = 127.42.0.1/24', state['config'])
            self.assertIn(b'Address = 127.42.0.2/32', state[next(key for key in state if key.startswith('peer-') and state[key].find(b'127.42.0.2') >= 0)])
            self.assertEqual(events[0], 'stop')
            self.assertEqual(events[-1], 'verify')
            self.assertIsNone(journal['files'])


if __name__ == '__main__':
    unittest.main()
