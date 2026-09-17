import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from awg_cita import cli


@unittest.skipUnless(os.name == "posix", "POSIX audit CLI contract")
class AuditCliTests(unittest.TestCase):
    def test_explicit_private_audit_path_constructs_audit_enabled_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            path = directory / "audit.jsonl"
            path.touch(mode=0o600)
            path.chmod(0o600)
            captured = {}

            class Server:
                def serve_forever(self):
                    captured["served"] = True

                def server_close(self):
                    captured["closed"] = True

            def create_server(_reader, host, port, allowed_hosts, audit_log):
                captured.update({"host": host, "port": port, "allowed_hosts": allowed_hosts, "audit_log": audit_log})
                return Server()

            with patch("awg_cita.cli.create_server", create_server):
                self.assertEqual(cli.main(["--binary", "/usr/local/bin/awg", "--interface", "awg0", "--audit-log", str(path)]), 0)

            self.assertEqual(captured["host"], "127.0.0.1")
            self.assertEqual(captured["port"], 8788)
            self.assertIsNone(captured["allowed_hosts"])
            self.assertIsNotNone(captured["audit_log"])
            self.assertTrue(captured["served"])
            self.assertTrue(captured["closed"])


if __name__ == "__main__":
    unittest.main()
