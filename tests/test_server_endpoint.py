import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from awg_cita.server_endpoint import project_client_endpoint, read_root_settings, replace_endpoint, revision, validate_request


CONFIG = ('[Interface]\nPrivateKey = SYNTHETIC\nAddress = 127.0.0.2/32\n'
          'DNS = 127.0.0.1\nMTU = 1420\n\n[Peer]\nPublicKey = SYNTHETIC\n'
          'Endpoint = old.example.org:47193\nAllowedIPs = 0.0.0.0/0\n'
          'PersistentKeepalive = 25\n')


class EndpointTests(unittest.TestCase):
    def test_projection_changes_only_endpoint_and_is_repeatable(self):
        changed = project_client_endpoint(CONFIG, 'new.example.org', 47193)
        self.assertEqual(changed, CONFIG.replace('old.example.org', 'new.example.org'))
        self.assertEqual(project_client_endpoint(changed, 'new.example.org', 47193), changed)
        self.assertEqual(project_client_endpoint(changed, 'old.example.org', 47193), CONFIG)
        moved = project_client_endpoint(CONFIG, 'new.example.org', 48193)
        self.assertIn('Endpoint = new.example.org:48193\n', moved)
        self.assertIn('PrivateKey = SYNTHETIC\n', moved)

    def test_projection_rejects_duplicate_wrong_port_and_injection(self):
        for text in (CONFIG.replace('Endpoint = ', 'Endpoint = bad.example.org:47193\nEndpoint = ', 1),
                     CONFIG.replace(':47193', ':47194'),
                     CONFIG.replace('[Peer]', 'Endpoint = old.example.org:47193\n[Peer]')):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    project_client_endpoint(text, 'new.example.org', 47193, expected_stored_port=47193)
        with self.assertRaises(ValueError):
            project_client_endpoint(CONFIG, 'new.example.org\nAllowedIPs = 0.0.0.0/0', 47193)

    def test_request_validation_and_revision(self):
        expected = revision(json.dumps({'endpoint_host': 'old.example.org'}).encode())
        self.assertEqual(validate_request({'expectedRevision': expected, 'endpoint': 'new.example.org'}),
                         (expected, 'new.example.org'))
        for endpoint in ('', '-invalid.example', 'bad host', 'host:123', 'host\nOther = value'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    validate_request({'expectedRevision': expected, 'endpoint': endpoint})

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                         'root-owned atomic file semantics required')
    def test_atomic_update_readback_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            path = root / 'profile.json'
            original = b'{"endpoint_host":"old.example.org","listen_port":47193}\n'
            path.write_bytes(original)
            path.chmod(0o600)
            with patch('awg_cita.server_endpoint.BACKUPS', root / 'backups'):
                updated = replace_endpoint(path, profile='wg', expected_revision=revision(original),
                                           endpoint='new.example.org', limit=512,
                                           verify=lambda: self.assertIn(b'new.example.org', read_root_settings(path, 512)))
                self.assertEqual(updated, revision(path.read_bytes()))
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(ValueError):
                    replace_endpoint(path, profile='wg', expected_revision=revision(original),
                                     endpoint='third.example.org', limit=512, verify=lambda: None)
                changed = path.read_bytes()
                with self.assertRaises(RuntimeError):
                    replace_endpoint(path, profile='wg', expected_revision=revision(changed),
                                     endpoint='third.example.org', limit=512,
                                     verify=lambda: (_ for _ in ()).throw(RuntimeError('verify failed')))
                self.assertEqual(path.read_bytes(), changed)


if __name__ == '__main__':
    unittest.main()
