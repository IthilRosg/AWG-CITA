import unittest

from awg_cita.audit import project_status_event


class AuditProjectionTests(unittest.TestCase):
    def test_projects_only_exact_safe_ok_event_with_writer_timestamp(self):
        snapshot = {
            "checked_at": "attacker-controlled-value",
            "state": "OK",
            "interface": "awg0",
            "peer_count": 2,
            "summary": {
                "total": 2,
                "online": 1,
                "stale": 0,
                "offline": 1,
                "never": 0,
                "unknown": 0,
                "rx_bytes": 1024,
                "tx_bytes": 2048,
            },
            "peers": [{"public_key": "must-not-persist"}],
            "raw_dump": "must-not-persist",
        }

        self.assertEqual(project_status_event(snapshot, checked_at="2026-09-17T12:00:00+00:00"), {
            "schema_version": 1,
            "kind": "status",
            "checked_at": "2026-09-17T12:00:00+00:00",
            "state": "OK",
            "peer_count": 2,
            "summary": {
                "total": 2,
                "online": 1,
                "stale": 0,
                "offline": 1,
                "never": 0,
                "unknown": 0,
                "rx_bytes": 1024,
                "tx_bytes": 2048,
            },
        })

    def test_rejects_boolean_summary_counter(self):
        snapshot = {
            "state": "OK",
            "peer_count": 1,
            "summary": {
                "total": 1,
                "online": True,
                "stale": 0,
                "offline": 0,
                "never": 0,
                "unknown": 0,
                "rx_bytes": 0,
                "tx_bytes": 0,
            },
        }

        with self.assertRaises(ValueError):
            project_status_event(snapshot, checked_at="2026-09-17T12:00:00+00:00")

    def test_projects_only_exact_safe_error_event(self):
        snapshot = {
            "state": "ERROR",
            "error_code": "awg_command_failed",
            "exception": "private command output must not persist",
            "stderr": "private stderr must not persist",
        }

        self.assertEqual(project_status_event(snapshot, checked_at="2026-09-17T12:00:00+00:00"), {
            "schema_version": 1,
            "kind": "status",
            "checked_at": "2026-09-17T12:00:00+00:00",
            "state": "ERROR",
            "error_code": "awg_command_failed",
        })

    def test_rejects_noncanonical_timestamp(self):
        snapshot = {"state": "ERROR", "error_code": "awg_command_failed"}

        with self.assertRaises(ValueError):
            project_status_event(snapshot, checked_at="private exception text")


if __name__ == "__main__":
    unittest.main()
