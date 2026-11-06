import base64
import ipaddress
import unittest

from awg_cita.client_templates import validate
from awg_cita.client_config_edit import editable_values, replace_editable
from awg_cita.lifecycle import LifecycleService
from awg_cita.real_awg import CanaryPeerController, PersistentCanaryConfig, RealAwgLifecycleAdapter


class WireGuardMigrationCompatibilityTests(unittest.TestCase):
    def test_124_dual_stack_peers_keep_disabled_state_and_psk(self):
        config = '[Interface]\nPrivateKey = fixture\nListenPort = 51820\n'
        rows = ['\t'.join(['fixture', 'fixture', '51820'] + ['0'] * 26)]
        keys = []
        for index in range(1, 125):
            key = base64.b64encode(index.to_bytes(32, 'big')).decode()
            keys.append(key)
            ipv4 = f'127.0.0.{index + 1}/32'
            ipv6 = f'{ipaddress.IPv6Address(index + 1)}/128'
            config += f'\n[Peer]\nPublicKey = {key}\nPresharedKey = {key}\nAllowedIPs = {ipv4}, {ipv6}\n'
            if index != 124:
                rows.append('\t'.join([key, key, '(none)', f'{ipv6},{ipv4}', '0', '0', '0', '0']))
        parsed = PersistentCanaryConfig(config.encode())
        disabled = parsed.disable(keys[-1])
        controller = CanaryPeerController(lambda: disabled, lambda: '\n'.join(rows) + '\n')
        records = controller.list_clients()
        self.assertEqual(len(records), 124)
        self.assertEqual(records[-1]['status'], 'DISABLED')
        self.assertEqual(PersistentCanaryConfig(disabled).enable(keys[-1]), config.encode())
        adapter = RealAwgLifecycleAdapter(lambda *_: {'schema_version': 1, 'clients': records})
        self.assertEqual(len(LifecycleService(adapter).list_clients()), 124)

    def test_config_editor_preserves_dual_addresses_and_psk(self):
        settings = validate({'dns_server': '127.0.0.1, ::1',
                             'allowed_ips': '0.0.0.0/0, ::/0', 'mtu': 1420, 'keepalive': 0})
        config = ('[Interface]\nPrivateKey = fixture\nAddress = 127.0.0.2/32, ::1/128\n'
                  'DNS = 127.0.0.1, ::1\nMTU = 1420\n\n[Peer]\n'
                  'PublicKey = fixture\nPresharedKey = fixture-psk\n'
                  'Endpoint = vpn.example.test:51820\nAllowedIPs = 0.0.0.0/0, ::/0\n'
                  'PersistentKeepalive = 0\n')
        self.assertEqual(editable_values(config), settings)
        self.assertEqual(replace_editable(config, settings), config)

    def test_duplicate_routes_and_dns_rejected(self):
        with self.assertRaises(ValueError):
            validate({'dns_server': '127.0.0.1, 127.0.0.1', 'allowed_ips': '::/0', 'mtu': 1420, 'keepalive': 0})


if __name__ == '__main__':
    unittest.main()
