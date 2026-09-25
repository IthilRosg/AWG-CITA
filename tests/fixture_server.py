"""Synthetic loopback server for browser tests; never use for deployment."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from awg_cita.app import AwgReader, create_server

INTERFACE = ["fixture-private", "fixture-public", "51820"] + ["0"] * 26
PEER = ["fixture-peer", "", "(none)", "", "1700000000", "1024", "2048", "off"]
DUMP = "\n".join(("\t".join(INTERFACE), "\t".join(PEER)))

if __name__ == "__main__":
    reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
    port = int(os.environ.get("AWG_FIXTURE_PORT", "0"))
    fixture_mode = os.environ.get("AWG_FIXTURE_MODE", "normal")
    if fixture_mode not in {"normal", "test"}:
        raise SystemExit("AWG_FIXTURE_MODE must be normal or test")
    server = create_server(reader, "127.0.0.1", port, test_mode=fixture_mode == "test")
    try:
        server.serve_forever()
    finally:
        server.server_close()
