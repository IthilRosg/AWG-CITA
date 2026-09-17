import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from awg_cita.audit import AuditLog


@unittest.skipUnless(os.name == "posix", "POSIX audit writer contract")
class AuditLogTests(unittest.TestCase):
    def test_appends_one_safe_jsonl_event_to_private_prepared_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            path = directory / "audit.jsonl"
            path.touch(mode=0o600)
            path.chmod(0o600)
            snapshot = {
                "state": "ERROR",
                "error_code": "awg_command_failed",
                "stderr": "must not persist",
            }

            audit_log = AuditLog.open(path, minimum_interval=60, clock=lambda: "2026-09-17T12:00:00+00:00")
            try:
                self.assertTrue(audit_log.record(snapshot))
            finally:
                audit_log.close()

            self.assertEqual([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()], [{
                "schema_version": 1,
                "kind": "status",
                "checked_at": "2026-09-17T12:00:00+00:00",
                "state": "ERROR",
                "error_code": "awg_command_failed",
            }])

    def test_suppresses_second_event_inside_minimum_interval(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            path = directory / "audit.jsonl"
            path.touch(mode=0o600)
            path.chmod(0o600)
            tick = iter((100.0, 120.0))
            snapshot = {"state": "ERROR", "error_code": "awg_command_failed"}

            audit_log = AuditLog.open(path, minimum_interval=60, clock=lambda: "2026-09-17T12:00:00+00:00", monotonic=lambda: next(tick))
            try:
                self.assertTrue(audit_log.record(snapshot))
                self.assertFalse(audit_log.record(snapshot))
            finally:
                audit_log.close()

            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_projection_failure_latches_before_later_interval_decision(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            path = directory / "audit.jsonl"
            path.touch(mode=0o600)
            path.chmod(0o600)
            tick = iter((100.0, 120.0))
            audit_log = AuditLog.open(path, minimum_interval=60, clock=lambda: "2026-09-17T12:00:00+00:00", monotonic=lambda: next(tick))
            try:
                with self.assertRaises(RuntimeError):
                    audit_log.record({"state": "ERROR", "error_code": "untrusted error"})
                with self.assertRaises(RuntimeError):
                    audit_log.record({"state": "ERROR", "error_code": "awg_command_failed"})
            finally:
                audit_log.close()

            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_external_growth_latches_before_next_append(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            path = directory / "audit.jsonl"
            path.touch(mode=0o600)
            path.chmod(0o600)
            tick = iter((100.0, 200.0))
            audit_log = AuditLog.open(path, minimum_interval=60, clock=lambda: "2026-09-17T12:00:00+00:00", monotonic=lambda: next(tick))
            try:
                self.assertTrue(audit_log.record({"state": "ERROR", "error_code": "awg_command_failed"}))
                with path.open("ab") as external:
                    external.write(b'{"foreign":true}\n')
                with self.assertRaises(RuntimeError):
                    audit_log.record({"state": "ERROR", "error_code": "awg_command_failed"})
            finally:
                audit_log.close()

    def test_retained_evidence_descriptor_is_write_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            path = directory / "audit.jsonl"
            path.touch(mode=0o600)
            path.chmod(0o600)
            original_open = os.open
            leaf_flags = []

            def tracking_open(name, flags, *args, **kwargs):
                if name == path.name and "dir_fd" in kwargs:
                    leaf_flags.append(flags)
                return original_open(name, flags, *args, **kwargs)

            with patch("awg_cita.audit.os.open", tracking_open):
                audit_log = AuditLog.open(path, minimum_interval=60, clock=lambda: "2026-09-17T12:00:00+00:00")
            audit_log.close()

            self.assertEqual(len(leaf_flags), 2)
            access_modes = [flags & os.O_ACCMODE for flags in leaf_flags]
            self.assertIn(os.O_WRONLY, access_modes)
            self.assertNotIn(os.O_RDWR, access_modes)

    def test_post_sync_external_append_latches_current_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            path = directory / "audit.jsonl"
            path.touch(mode=0o600)
            path.chmod(0o600)
            audit_log = AuditLog.open(path, minimum_interval=60, clock=lambda: "2026-09-17T12:00:00+00:00")
            original_fsync = os.fsync

            def foreign_fsync(descriptor):
                original_fsync(descriptor)
                with path.open("ab") as external:
                    external.write(b'{"foreign":true}\n')

            try:
                with patch("awg_cita.audit.os.fsync", foreign_fsync):
                    with self.assertRaises(RuntimeError):
                        audit_log.record({"state": "ERROR", "error_code": "awg_command_failed"})
            finally:
                audit_log.close()


if __name__ == "__main__":
    unittest.main()
