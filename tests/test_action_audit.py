"""Action evidence recovery and file integrity checks."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from awg_cita.audit import ActionAuditLog, project_action_event, project_action_history


EVENT = dict(phase='INTENT', correlation_id='a' * 32, actor='operator-1',
             operation='disable', client_id='peer-0123456789abcdef', nonce_digest='b' * 64)


class ActionProjectionTests(unittest.TestCase):
    def test_action_history_is_bounded_and_excludes_private_fields(self):
        events = [project_action_event(checked_at='2026-09-25T00:00:00+00:00',
                                      **dict(EVENT, correlation_id=f'{index:032x}')) for index in range(205)]
        raw = b''.join((json.dumps(event, separators=(',', ':')) + '\n').encode() for event in events)
        result = project_action_history(raw)
        self.assertEqual((result['schema_version'], result['source'], result['truncated']), (1, 'server_audit', True))
        self.assertEqual(len(result['events']), 200)
        self.assertEqual(result['events'][0]['correlation_id'], f'{5:032x}')
        self.assertEqual(result['events'][-1]['correlation_id'], f'{204:032x}')
        self.assertEqual(set(result['events'][0]), {'checked_at', 'phase', 'correlation_id', 'actor', 'operation', 'client_id'})
        self.assertNotIn('nonce_digest', json.dumps(result))
        self.assertNotIn(EVENT['nonce_digest'], json.dumps(result))
        self.assertEqual(project_action_history(b'')['events'], [])
        self.assertFalse(project_action_history(b'')['truncated'])

    def test_action_history_rejects_corruption_without_partial_results(self):
        event = project_action_event(checked_at='2026-09-25T00:00:00+00:00', **EVENT)
        valid = (json.dumps(event, separators=(',', ':')) + '\n').encode()
        bad = [b'not-json\n', valid[:-1], b'[]\n', b'{}\n', b'\xff\n', b'x' * 1048577,
               (json.dumps(dict(event, secret='fake')) + '\n').encode(),
               (json.dumps(dict(event, schema_version=True)) + '\n').encode(),
               valid.replace(b'"phase":"INTENT"', b'"phase":"RESULT","phase":"INTENT"')]
        for raw in bad:
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                project_action_history(raw)
        # A corrupt older record must not be hidden by a valid 200-record tail.
        with self.assertRaises(ValueError):
            project_action_history(b'{}\n' + valid * 200)
        result_event = project_action_event(checked_at='2026-09-25T00:00:00+00:00',
                                           **dict(EVENT, phase='RESULT', result='OK'))
        self.assertEqual(project_action_history((json.dumps(result_event) + '\n').encode())['events'][0]['result'], 'OK')

    def test_projection_contains_only_safe_fields(self):
        event = project_action_event(checked_at='2026-09-25T00:00:00+00:00', **EVENT)
        self.assertEqual(set(event), {'schema_version', 'kind', 'checked_at', *EVENT})
        self.assertNotIn('secret', json.dumps(event))
        with self.assertRaises(ValueError):
            project_action_event(checked_at='2026-09-25T00:00:00+00:00', **dict(EVENT, actor='bad actor'))

    def test_settings_actions_are_safe_and_accepted(self):
        for profile in ('awg3', 'awg2', 'wg'):
            for operation in ('template', 'config_update', 'endpoint_update', 'port_update'):
                with self.subTest(profile=profile, operation=operation):
                    event = project_action_event(checked_at='2026-09-25T00:00:00+00:00',
                                                 **dict(EVENT, operation=profile + '_' + operation,
                                                        client_id=''))
                    self.assertEqual(event['operation'], profile + '_' + operation)
                    self.assertNotIn('endpoint', event)


@unittest.skipUnless(os.name == 'posix', 'POSIX file ownership semantics required')
class ActionFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'actions.jsonl'

    def open(self):
        return ActionAuditLog.open(self.path, clock=lambda: '2026-09-25T00:00:00+00:00')

    def test_unmatched_intent_blocks_restart(self):
        log = self.open()
        log.record_action(**EVENT)
        log.close()
        with self.assertRaisesRegex(ValueError, 'unmatched action audit intent'):
            self.open()

    def test_paired_events_reopen(self):
        log = self.open()
        log.record_action(**EVENT)
        log.record_action(**dict(EVENT, phase='RESULT', result='OK'))
        log.close()
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(len(self.path.read_text().splitlines()), 2)
        reopened = self.open()
        reopened.close()

    def test_recent_actions_validates_file_and_does_not_write(self):
        log = self.open()
        self.addCleanup(log.close)
        log.record_action(**EVENT)
        log.record_action(**dict(EVENT, phase='RESULT', result='OK'))
        before = self.path.read_bytes()
        result = log.recent_actions()
        self.assertEqual(len(result['events']), 2)
        self.assertEqual(result['events'][-1]['result'], 'OK')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn('nonce_digest', json.dumps(result))
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            log.recent_actions()

    def test_recent_actions_rejects_replacement_and_external_append(self):
        log = self.open()
        self.addCleanup(log.close)
        moved = self.path.with_suffix('.original')
        self.path.rename(moved)
        self.path.symlink_to(moved)
        with self.assertRaises((OSError, ValueError)):
            log.recent_actions()
        self.path.unlink()
        moved.rename(self.path)
        with self.path.open('ab') as stream:
            stream.write(b'{}\n')
        with self.assertRaises(ValueError):
            log.recent_actions()

    def test_external_append_latches_writer(self):
        log = self.open()
        with self.path.open('ab') as writer:
            writer.write(b'{}\n')
        with self.assertRaises(RuntimeError):
            log.record_action(**EVENT)
        log.close()

    def test_fsync_failure_latches_writer(self):
        log = self.open()
        with patch('awg_cita.audit.os.fsync', side_effect=OSError('failure')):
            with self.assertRaises(RuntimeError):
                log.record_action(**EVENT)
        with self.assertRaises(RuntimeError):
            log.record_action(**EVENT)
        log.close()

    def test_symlink_and_unsafe_mode_refused(self):
        target = Path(self.directory.name) / 'target'
        target.write_text('')
        self.path.symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            self.open()
        self.path.unlink()
        self.path.write_text('')
        os.chmod(self.path, 0o644)
        with self.assertRaises(ValueError):
            self.open()


if __name__ == '__main__':
    unittest.main()
