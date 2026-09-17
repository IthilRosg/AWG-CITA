import unittest

from awg_cita.history import SnapshotHistory


class SnapshotHistoryTests(unittest.TestCase):
    def test_default_limit_evicts_oldest_entry_after_sixty_records(self):
        history = SnapshotHistory()
        for index in range(61):
            history.record({
                "checked_at": f"2026-09-17T00:{index:02d}:00+00:00",
                "state": "ERROR",
                "error_code": "awg_command_failed",
            })

        records = history.records()
        self.assertEqual(len(records), 60)
        self.assertEqual(records[0]["checked_at"], "2026-09-17T00:01:00+00:00")
        self.assertEqual(records[-1]["checked_at"], "2026-09-17T00:60:00+00:00")

    def test_records_a_bounded_safe_projection_of_snapshots(self):
        history = SnapshotHistory(limit=2)
        history.record({
            "schema_version": 1,
            "state": "OK",
            "checked_at": "2026-09-17T00:00:00+00:00",
            "interface": "awg0",
            "peer_count": 1,
            "summary": {"total": 1, "online": 1, "stale": 0, "offline": 0, "never": 0, "unknown": 0, "rx_bytes": 1024, "tx_bytes": 2048},
            "peers": [{"latest_handshake": 1, "rx_bytes": 1024, "tx_bytes": 2048, "status": "ONLINE"}],
            "raw_dump": "must not persist",
        })
        history.record({
            "schema_version": 1,
            "state": "ERROR",
            "error_code": "awg_command_failed",
            "checked_at": "2026-09-17T00:01:00+00:00",
            "interface": "awg0",
            "peer_count": 99,
            "summary": {"rx_bytes": 999},
            "secret": "must not persist",
        })
        history.record({
            "schema_version": 1,
            "state": "OK",
            "checked_at": "2026-09-17T00:02:00+00:00",
            "interface": "awg0",
            "peer_count": 2,
            "summary": {"total": 2, "online": 1, "stale": 1, "offline": 0, "never": 0, "unknown": 0, "rx_bytes": 4096, "tx_bytes": 8192},
        })

        self.assertEqual(history.records(), [
            {
                "checked_at": "2026-09-17T00:01:00+00:00",
                "state": "ERROR",
                "error_code": "awg_command_failed",
            },
            {
                "checked_at": "2026-09-17T00:02:00+00:00",
                "state": "OK",
                "peer_count": 2,
                "summary": {"total": 2, "online": 1, "stale": 1, "offline": 0, "never": 0, "unknown": 0, "rx_bytes": 4096, "tx_bytes": 8192},
            },
        ])


if __name__ == "__main__":
    unittest.main()
