import unittest

from awg_cita.snapshot import build_snapshot, parse_awg_dump


INTERFACE = ["fixture-private", "fixture-public", "51820"] + ["0"] * 26
PEER = ["fixture-peer", "", "(none)", "", "1700000000", "1024", "2048", "off"]
DUMP = "\n".join(("\t".join(INTERFACE), "\t".join(PEER)))


class SnapshotTests(unittest.TestCase):
    def test_parser_returns_only_safe_counters(self):
        parsed = parse_awg_dump(DUMP)

        self.assertEqual(parsed["listen_port"], 51820)
        self.assertEqual(parsed["peers"], [{"latest_handshake": 1700000000, "rx_bytes": 1024, "tx_bytes": 2048}])
        self.assertNotIn("fixture-private", repr(parsed))
        self.assertNotIn("fixture-public", repr(parsed))
        self.assertNotIn("fixture-peer", repr(parsed))

    def test_snapshot_calculates_safe_aggregates(self):
        snapshot = build_snapshot(DUMP, now=1700000030, interface="awg0")

        self.assertEqual(snapshot["summary"]["total"], 1)
        self.assertEqual(snapshot["summary"]["online"], 1)
        self.assertEqual(snapshot["summary"]["rx_bytes"], 1024)
        self.assertEqual(snapshot["summary"]["tx_bytes"], 2048)
        self.assertEqual(snapshot["peers"][0]["status"], "ONLINE")
        self.assertNotIn("fixture-peer", repr(snapshot))


if __name__ == "__main__":
    unittest.main()
