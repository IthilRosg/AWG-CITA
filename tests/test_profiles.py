"""Additional-profile contracts without touching real interfaces."""
import importlib.util
import unittest
from pathlib import Path

from awg_cita.client_templates import validate


class ClientTemplateTests(unittest.TestCase):
    def test_split_route_template_is_canonical_and_bounded(self):
        value = validate({'dns_server': '127.0.0.1', 'allowed_ips': '127.0.0.0/8, 127.1.0.0/16',
                          'mtu': 1420, 'keepalive': 25})
        self.assertEqual(value['allowed_ips'], '127.0.0.0/8, 127.1.0.0/16')
        for routes in ('127.0.0.1/8', '127.0.0.0/8, 127.0.0.0/8', '::/0', '0.0.0.0/0; PostUp = bad'):
            with self.subTest(routes=routes), self.assertRaises(ValueError):
                validate({**value, 'allowed_ips': routes})

    def test_server_parameters_are_absent_from_plain_wg_config(self):
        path = Path(__file__).parents[1] / 'scripts' / 'install-additional-profiles.py'
        spec = importlib.util.spec_from_file_location('profile_installer', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plain = module.config_text('wg', 'awg-cita-wg', '127.0.1.1/24', 47194,
                                   'ens3', 'synthetic-private-key', {})
        awg = module.config_text('awg2', 'awg-cita2', '127.0.0.1/24', 47193,
                                 'ens3', 'synthetic-private-key', module.profile_values('awg2'))
        self.assertNotIn('HeaderProtectionKey', plain + awg)
        for key in ('S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4', 'Jc', 'Jmin', 'Jmax'):
            self.assertNotIn(f'{key} =', plain)
            self.assertIn(f'{key} =', awg)
