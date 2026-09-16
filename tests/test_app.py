import threading
import unittest
from http.client import HTTPConnection

from awg_cita.app import AwgReader, create_server


INTERFACE = ["fixture-private", "fixture-public", "51820"] + ["0"] * 26
PEER = ["fixture-peer", "", "(none)", "", "1700000000", "1024", "2048", "off"]
DUMP = "\n".join(("\t".join(INTERFACE), "\t".join(PEER)))


class ApiTests(unittest.TestCase):
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
            self.assertIn('"interface":"awg0"', body)
            self.assertNotIn("fixture-private", body)
            self.assertNotIn("fixture-public", body)
            self.assertNotIn("fixture-peer", body)

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


if __name__ == "__main__":
    unittest.main()
