import re
import unittest

from scripts.check_public_safety import PATTERNS, public_ip_literals


class PublicSafetyTests(unittest.TestCase):
    def test_credential_patterns_detect_synthetic_secret_forms(self):
        values = {
            "private_key_block": "-----BEGIN " + "PRIVATE KEY-----",
            "bcrypt_hash": "$2b$12$" + "a" * 53,
            "awg_or_wireguard_uri": "wire" + "guard://fixture",
            "github_token": "gh" + "p_" + "a" * 20,
            "openai_key": "s" + "k-" + "a" * 20,
            "gitlab_token": "gl" + "pat-" + "a" * 20,
            "google_api_key": "AI" + "za" + "a" * 20,
            "jwt": "eyJ" + "a" * 8 + "." + "b" * 8 + "." + "c" * 8,
            "aws_access_key": "AK" + "IA" + "A" * 16,
            "slack_token": "xox" + "b-" + "a" * 10,
            "sensitive_assignment": "api" + "_token=" + "a" * 8,
            "wireguard_style_key": "A" * 43 + "=",
        }
        for label, value in values.items():
            with self.subTest(label=label):
                self.assertIsNotNone(re.search(PATTERNS[label], value))

    def test_public_ip_literals_detects_ipv4_and_ipv6_endpoint_forms(self):
        ipv4 = ".".join(("203", "0", "113", "10"))
        ipv6 = "2001" + ":db8::1"
        text = f"peer={ipv4}:8080 and peer=[{ipv6}]:51820 and loopback=127.0.0.1"
        self.assertEqual(public_ip_literals(text), [ipv4, ipv6])


if __name__ == "__main__":
    unittest.main()
