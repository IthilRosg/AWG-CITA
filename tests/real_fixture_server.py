"""Local synthetic same-origin canary UI fixture; never deploy to a production host."""
import os
import sys
import json
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from awg_cita.app import AwgReader, create_server
from awg_cita.lifecycle import FakeAwgLifecycleAdapter, LifecycleService
from awg_cita.audit import project_action_event, project_action_history


class MemoryActionAudit:
    """Synthetic browser-fixture evidence; never used by production."""
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def record_action(self, **fields):
        event = project_action_event(checked_at='2026-09-25T00:00:00+00:00', **fields)
        with self.lock:
            self.events.append(event)

    def recent_actions(self):
        with self.lock:
            raw = b''.join((json.dumps(event, separators=(',', ':')) + '\n').encode() for event in self.events)
        return project_action_history(raw)

PEER_ID = 'peer-0123456789abcdef'
RECORDS = [
    {'id': PEER_ID, 'name': 'Disposable Peer', 'status': 'NEVER', 'lastHandshakeAt': None,
     'lastSeenAt': None, 'createdAt': None, 'expiration': '', 'rxBytes': 0, 'txBytes': 0,
     'notes': '', 'tags': [], 'warning': ''},
]
interface = ['fixture-private', 'fixture-public', '51820'] + ['0'] * 26
peer = ['fixture-peer', '', '(none)', '127.0.1.254/32', '0', '0', '0', 'off']
dump = '\n'.join(('\t'.join(interface), '\t'.join(peer))) + '\n'
if __name__ == '__main__':
    port = int(os.environ['AWG_FIXTURE_PORT'])
    reader = AwgReader(binary='/unused', interface='awg-canary0', runner=lambda *_: (dump, ''))
    server = create_server(reader, '127.0.0.1', port,
                           lifecycle_service=LifecycleService(FakeAwgLifecycleAdapter(RECORDS)),
                           action_audit_log=MemoryActionAudit(),
                           operator_origin=f'http://127.0.0.1:{port}', test_mode=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
