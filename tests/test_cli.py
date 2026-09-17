import unittest
from unittest.mock import patch

from awg_cita import cli


class CliTests(unittest.TestCase):
    def test_main_constructs_loopback_server_with_explicit_safe_values(self):
        captured = {}

        class Server:
            def serve_forever(self):
                captured["served"] = True

            def server_close(self):
                captured["closed"] = True

        def create_server(reader, host, port, allowed_hosts):
            captured.update({"binary": reader.binary, "interface": reader.interface, "host": host, "port": port, "allowed_hosts": allowed_hosts})
            return Server()

        with patch("awg_cita.cli.create_server", create_server):
            self.assertEqual(cli.main(["--binary", "/usr/local/bin/awg", "--interface", "awg0", "--port", "8788", "--allowed-host", "panel.example"]), 0)

        self.assertEqual(captured, {"binary": "/usr/local/bin/awg", "interface": "awg0", "host": "127.0.0.1", "port": 8788, "allowed_hosts": frozenset({"panel.example"}), "served": True, "closed": True})

    def test_main_refuses_non_loopback_bind(self):
        wildcard_bind = ".".join(["0"] * 4)
        with self.assertRaises(SystemExit) as raised:
            cli.main(["--binary", "/usr/local/bin/awg", "--interface", "awg0", "--bind", wildcard_bind])
        self.assertEqual(raised.exception.code, 2)

    def test_main_refuses_malformed_allowed_host(self):
        with self.assertRaises(SystemExit) as raised:
            cli.main(["--binary", "/usr/local/bin/awg", "--interface", "awg0", "--allowed-host", "bad host"])
        self.assertEqual(raised.exception.code, 2)

    def test_main_refuses_invalid_awg_reader_values(self):
        with self.assertRaises(SystemExit) as raised:
            cli.main(["--binary", "awg", "--interface", "awg0"])
        self.assertEqual(raised.exception.code, 2)

    def test_main_uses_default_loopback_hosts_when_no_proxy_host_is_given(self):
        captured = {}

        class Server:
            def serve_forever(self):
                pass

            def server_close(self):
                pass

        def create_server(_reader, host, port, allowed_hosts):
            captured["allowed_hosts"] = allowed_hosts
            return Server()

        with patch("awg_cita.cli.create_server", create_server):
            self.assertEqual(cli.main(["--binary", "/usr/local/bin/awg", "--interface", "awg0"]), 0)
        self.assertIsNone(captured["allowed_hosts"])

    def test_main_refuses_audit_interval_without_an_audit_log(self):
        with patch("awg_cita.cli.create_server", side_effect=AssertionError("must not start server")):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--binary", "/usr/local/bin/awg", "--interface", "awg0", "--audit-min-interval", "60"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
