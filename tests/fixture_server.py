"""Synthetic loopback server for browser tests; never use for deployment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from awg_cita.app import AwgReader, create_server

INTERFACE = ["fixture-private", "fixture-public", "51820"] + ["0"] * 26
PEER = ["fixture-peer", "", "(none)", "", "1700000000", "1024", "2048", "off"]
DUMP = "\n".join(("\t".join(INTERFACE), "\t".join(PEER)))

if __name__ == "__main__":
    reader = AwgReader(binary="/usr/local/bin/awg", interface="awg0", runner=lambda _argv, _timeout: (DUMP, ""), clock=lambda: 1700000030)
    create_server(reader, "127.0.0.1", 8791).serve_forever()
