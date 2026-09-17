import json
import os
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from awg_cita.app import AwgReader, create_server
from awg_cita.audit import AuditLog


INTERFACE = ["fixture-private", "fixture-public", "51820"] + ["0"] * 26
PEER = ["fixture-peer", "", "(none)", "", "1700000000", "1024", "2048", "off"]
DUMP = "\n".join(("\t".join(INTERFACE), "\t".join(PEER)))


@unittest.skipUnless(os.name == "posix", "POSIX audit HTTP contract")
class AuditHttpTests(unittest.TestCase):
    def test_safe_status_appends_one_safe_event_without_changing_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            path = directory / "audit.jsonl"
            path.touch(mode=0o600)
            path.chmod(0o600)
            audit_log = AuditLog.open(path, minimum_interval=60, clock=lambda: "2026-09-17T12:00:00+00:00")
            reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
            server = create_server(reader, "127.0.0.1", 0, audit_log=audit_log)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
                connection.request("GET", "/api/status")
                response = connection.getresponse()
                body = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn('"interface":"awg0"', body)
                self.assertNotIn("fixture-private", body)
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                audit_log.close()

            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["state"], "OK")
            self.assertNotIn("interface", records[0])
            self.assertNotIn("peers", records[0])

    def test_audit_failure_returns_generic_503_without_history_entry(self):
        class FailingAuditLog:
            def record(self, _snapshot):
                raise RuntimeError("private audit write failure")

        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
        server = create_server(reader, "127.0.0.1", 0, audit_log=FailingAuditLog())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            connection.request("GET", "/api/status")
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 503)
            self.assertEqual(json.loads(body)["error_code"], "audit_write_failed")
            self.assertNotIn("private audit write failure", body)
            connection.request("GET", "/api/history")
            self.assertEqual(json.loads(connection.getresponse().read().decode("utf-8"))["history"], [])
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_latched_audit_failure_returns_before_awg_read(self):
        class LatchedAuditLog:
            def preflight(self):
                raise RuntimeError("latched")

            def record(self, _snapshot):
                raise AssertionError("must not record")

        calls = []
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (calls.append("read"), (DUMP, ""))[1], clock=lambda: 1700000030)
        server = create_server(reader, "127.0.0.1", 0, audit_log=LatchedAuditLog())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            connection.request("GET", "/api/status")
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            self.assertEqual(json.loads(response.read().decode("utf-8"))["error_code"], "audit_write_failed")
            self.assertEqual(calls, [])
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
