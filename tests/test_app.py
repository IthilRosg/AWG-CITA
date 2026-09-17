import threading
import unittest
from http.client import HTTPConnection
import socket
import sys
import time

from awg_cita.app import AwgCommandOutputError, MAX_AWG_DUMP_BYTES, AwgOutputTooLarge, AwgReader, create_server


INTERFACE = ["fixture-private", "fixture-public", "51820"] + ["0"] * 26
PEER = ["fixture-peer", "", "(none)", "", "1700000000", "1024", "2048", "off"]
DUMP = "\n".join(("\t".join(INTERFACE), "\t".join(PEER)))


class ApiTests(unittest.TestCase):
    def test_default_runner_does_not_wait_for_descendant_pipe_handles(self):
        argv = (sys.executable, "-c", "import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)']); sys.stdout.buffer.write(b'x' * 1048577); sys.stdout.flush()")
        started = time.monotonic()
        with self.assertRaises(AwgOutputTooLarge):
            AwgReader._run(argv, 3)
        self.assertLess(time.monotonic() - started, 4)

    def test_default_runner_rejects_invalid_utf8_stdout(self):
        argv = (sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff')")
        with self.assertRaises(AwgCommandOutputError):
            AwgReader._run(argv, 3)

    def test_default_runner_terminates_child_after_output_limit(self):
        argv = (sys.executable, "-c", "import sys,time; sys.stdout.buffer.write(b'x' * 1048577); sys.stdout.flush(); time.sleep(10)")
        with self.assertRaises(AwgOutputTooLarge):
            AwgReader._run(argv, 3)

    def test_default_runner_allows_output_at_limit(self):
        argv = (sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 1048576)")
        stdout, _stderr = AwgReader._run(argv, 3)
        self.assertEqual(len(stdout.encode("utf-8")), MAX_AWG_DUMP_BYTES)

    def test_oversized_awg_output_fails_closed(self):
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: ("x" * 1_048_577, ""), clock=lambda: 1700000030)
        snapshot = reader.snapshot()
        self.assertEqual(snapshot["state"], "ERROR")
        self.assertEqual(snapshot["error_code"], "awg_output_too_large")

    def test_explicit_allowed_hosts_must_be_canonical_hostnames_or_loopback_ips(self):
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
        ambiguous_numeric_name = "127" + ".0.0.01"
        for hosts in (frozenset({"panel.example:8444"}), frozenset({"bad host"}), frozenset({"Panel.Example"}), frozenset({"[::1]"}), frozenset({ambiguous_numeric_name})):
            with self.subTest(hosts=hosts):
                with self.assertRaises(ValueError):
                    create_server(reader, "127.0.0.1", 0, allowed_hosts=hosts)

    def test_loopback_api_is_safe_and_read_only(self):
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
        server = create_server(reader, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            connection.request("GET", "/api/status")
            response = connection.getresponse()
            body = response.read().decode()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("X-Frame-Options"), "DENY")
            self.assertEqual(response.getheader("Content-Security-Policy"), "default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.assertIn('"interface":"awg0"', body)
            self.assertNotIn("fixture-private", body)
            self.assertNotIn("fixture-public", body)
            self.assertNotIn("fixture-peer", body)

            connection.request("GET", "/static/sector-console.css")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "text/css; charset=utf-8")
            self.assertIn("--bg", response.read().decode())

            connection.request("GET", "/static/sector-console.js")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "application/javascript; charset=utf-8")
            self.assertIn("async function refresh", response.read().decode())

            connection.request("GET", "/api/status", headers={"Host": "untrusted.example"})
            response = connection.getresponse()
            self.assertEqual(response.status, 421)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            response.read()

            for host in ("[::1]evil", "[::1].attacker", "[::1]:99999", "[127.0.0.1]", "", "localhost:bad"):
                connection.request("GET", "/api/status", headers={"Host": host})
                response = connection.getresponse()
                self.assertEqual(response.status, 421, host)
                response.read()

            connection.request("HEAD", "/")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"")

            connection.request("OPTIONS", "/other")
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()

            connection.request("POST", "/api/status", body=b"{}")
            response = connection.getresponse()
            self.assertEqual(response.status, 405)
            self.assertEqual(response.getheader("Allow"), "GET, HEAD, OPTIONS")
            response.read()
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_explicit_proxy_host_allows_only_valid_host_and_port(self):
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
        server = create_server(reader, "127.0.0.1", 0, allowed_hosts=frozenset({"panel.example"}))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            connection.request("GET", "/api/status", headers={"Host": "panel.example:8444"})
            self.assertEqual(connection.getresponse().status, 200)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_safe_status_records_a_sanitized_history_entry(self):
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
        server = create_server(reader, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            connection.request("GET", "/api/status")
            self.assertEqual(connection.getresponse().status, 200)
            connection.request("GET", "/api/history")
            response = connection.getresponse()
            body = response.read().decode()
            self.assertEqual(response.status, 200)
            self.assertIn('"state":"OK"', body)
            self.assertNotIn("fixture-private", body)
            self.assertNotIn("fixture-public", body)
            self.assertNotIn("fixture-peer", body)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_history_rejects_untrusted_host_and_records_generic_error_only(self):
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (_ for _ in ()).throw(RuntimeError("fixture command output must not escape")))
        server = create_server(reader, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            connection.request("GET", "/api/history", headers={"Host": "untrusted.example"})
            self.assertEqual(connection.getresponse().status, 421)
            connection.request("GET", "/api/status")
            self.assertEqual(connection.getresponse().status, 503)
            connection.request("GET", "/api/history")
            response = connection.getresponse()
            body = response.read().decode()
            self.assertEqual(response.status, 200)
            self.assertIn('"error_code":"awg_command_failed"', body)
            self.assertNotIn("fixture command output", body)
            self.assertNotIn('"peers"', body)
            self.assertNotIn('"summary"', body)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


    def test_explicit_empty_host_allowlist_denies_all_requests(self):
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
        server = create_server(reader, "127.0.0.1", 0, allowed_hosts=frozenset())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            connection.request("GET", "/api/status")
            self.assertEqual(connection.getresponse().status, 421)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


    def test_ipv6_loopback_server_serves_safe_status(self):
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
        server = create_server(reader, "::1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("::1", server.server_address[1], timeout=3)
            connection.request("GET", "/api/status", headers={"Host": "[::1]"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn('"interface":"awg0"', response.read().decode())
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


    def test_duplicate_host_headers_are_rejected(self):
        reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
        server = create_server(reader, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=3) as connection:
                connection.sendall(b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\nHost: attacker.example\r\nConnection: close\r\n\r\n")
                response = connection.recv(4096)
            self.assertIn(b" 421 ", response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
