"""Safe command-line launcher for the read-only AWG CITA server."""

from __future__ import annotations

import argparse

from .app import AwgReader, create_server


def port(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the read-only AWG CITA loopback server.")
    parser.add_argument("--binary", required=True, help="Absolute path to the allowlisted AWG executable.")
    parser.add_argument("--interface", required=True, help="AWG interface name to inspect.")
    parser.add_argument("--bind", choices=("127.0.0.1", "::1"), default="127.0.0.1", help="Loopback address only.")
    parser.add_argument("--port", type=port, default=8788, help="Loopback TCP port (default: 8788).")
    parser.add_argument("--allowed-host", action="append", default=None, help="Explicit reverse-proxy Host name; may be repeated. No port or bracket syntax.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    allowed_hosts = frozenset(arguments.allowed_host) if arguments.allowed_host else None
    try:
        reader = AwgReader(binary=arguments.binary, interface=arguments.interface)
        server = create_server(reader, host=arguments.bind, port=arguments.port, allowed_hosts=allowed_hosts)
    except ValueError as error:
        parser.error(str(error))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
