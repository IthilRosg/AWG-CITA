import unittest

from awg_cita.client_config_edit import editable_values, replace_editable, revision


CONFIG = ('[Interface]\nPrivateKey = SYNTHETIC-ONLY\nAddress = 127.0.0.2/32\n'
          'DNS = 127.0.0.1\nMTU = 1420\nS1 = 20\n\n[Peer]\n'
          'PublicKey = SYNTHETIC-SERVER\nEndpoint = example.test:47193\n'
          'AllowedIPs = 0.0.0.0/0\nPersistentKeepalive = 25\n')


class SavedConfigEditTests(unittest.TestCase):
    def test_only_editable_fields_change_and_revision_advances(self):
        settings = {'dns_server': '127.0.0.2', 'allowed_ips': '127.0.0.0/8',
                    'mtu': 1280, 'keepalive': 15}
        updated = replace_editable(CONFIG, settings)
        self.assertEqual(editable_values(updated), settings)
        for protected in ('PrivateKey = SYNTHETIC-ONLY', 'Address = 127.0.0.2/32',
                          'S1 = 20', 'PublicKey = SYNTHETIC-SERVER', 'Endpoint = example.test:47193'):
            self.assertIn(protected, updated)
        self.assertNotEqual(revision(CONFIG), revision(updated))

    def test_legacy_config_without_mtu_can_be_edited(self):
        old = CONFIG.replace('MTU = 1420\n', '')
        self.assertEqual(editable_values(old)['mtu'], 1420)
        updated = replace_editable(old, editable_values(old))
        self.assertEqual(updated.count('MTU = 1420'), 1)

    def test_injection_and_duplicate_editable_fields_rejected(self):
        settings = editable_values(CONFIG)
        with self.assertRaises(ValueError):
            replace_editable(CONFIG, {**settings, 'dns_server': '127.0.0.1\nPostUp = bad'})
        with self.assertRaises(ValueError):
            replace_editable(CONFIG.replace('DNS = 127.0.0.1\n', 'DNS = 127.0.0.1\nDNS = 127.0.0.2\n'), settings)


if __name__ == '__main__':
    unittest.main()
