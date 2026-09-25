"""Command-line launcher for AWG CITA and its optional canary actions."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlsplit

from .app import CANARY_SOCKET_PATH, AwgReader, create_server
from .audit import ActionAuditLog, AuditLog
from .lifecycle import LifecycleService
from .real_awg import RealAwgLifecycleAdapter


def port(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return parsed


def audit_interval(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("audit interval must be an integer") from error
    if not 60 <= parsed <= 3600:
        raise argparse.ArgumentTypeError("audit interval must be between 60 and 3600 seconds")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AWG CITA in read-only or private canary mode.")
    parser.add_argument("--binary", required=True, help="Absolute path to the allowlisted AWG executable.")
    parser.add_argument("--interface", required=True, help="AWG interface name to inspect.")
    parser.add_argument("--bind", choices=("127.0.0.1", "::1"), default="127.0.0.1", help="Loopback address only.")
    parser.add_argument("--port", type=port, default=8788, help="Loopback TCP port (default: 8788).")
    parser.add_argument("--allowed-host", action="append", default=None, help="Explicit reverse-proxy Host name; may be repeated. No port or bracket syntax.")
    parser.add_argument("--audit-log", type=Path, help="Absolute POSIX path to an operator-prepared private JSONL evidence file.")
    parser.add_argument("--audit-min-interval", type=audit_interval, default=None, help="Evidence sampling interval in seconds (60-3600; default: 60). Requires --audit-log.")
    parser.add_argument("--canary-actions", action="store_true", help="Enable only the fixed awg-canary0 lifecycle helper.")
    parser.add_argument("--operator-origin", help="HTTPS origin of the authenticated operator proxy, required with canary actions.")
    parser.add_argument("--operator-id", help="Fixed operator identifier supplied by the trusted proxy.")
    parser.add_argument("--action-audit-log", type=Path, help="Absolute private JSONL path for durable action evidence.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    allowed_hosts = frozenset(arguments.allowed_host) if arguments.allowed_host else None
    if arguments.audit_log is None and arguments.audit_min_interval is not None:
        parser.error("--audit-min-interval requires --audit-log")
    if (arguments.audit_log is not None and arguments.action_audit_log is not None and
            arguments.audit_log == arguments.action_audit_log):
        parser.error("status and action audit files must be separate")
    audit_log = None
    action_audit_log = None
    server = None
    try:
        reader = AwgReader(binary=arguments.binary, interface=arguments.interface)
        parsed_origin = urlsplit(arguments.operator_origin or '')
        if arguments.canary_actions and (arguments.interface != 'awg-canary0' or
                                         parsed_origin.scheme != 'https' or not parsed_origin.hostname or
                                         parsed_origin.netloc.endswith(':') or
                                         (parsed_origin.port is not None and not 1 <= parsed_origin.port <= 65535) or
                                         parsed_origin.username is not None or parsed_origin.password is not None or
                                         parsed_origin.path or parsed_origin.query or parsed_origin.fragment or
                                         allowed_hosts != frozenset({parsed_origin.hostname})):
            parser.error('canary actions require awg-canary0 and a matching HTTPS operator origin')
        if arguments.operator_origin and not arguments.canary_actions:
            parser.error('--operator-origin requires --canary-actions')
        if arguments.canary_actions and (not arguments.operator_id or arguments.action_audit_log is None):
            parser.error('--canary-actions requires --operator-id and --action-audit-log')
        if not arguments.canary_actions and (arguments.operator_id or arguments.action_audit_log):
            parser.error('--operator-id and --action-audit-log require --canary-actions')
        service = LifecycleService(RealAwgLifecycleAdapter()) if arguments.canary_actions else None
        origin = arguments.operator_origin if arguments.canary_actions else None
        if service is not None:
            action_audit_log = ActionAuditLog.open(arguments.action_audit_log)
        canary_options = {'lifecycle_service': service, 'operator_origin': origin,
                          'operator_id': arguments.operator_id, 'action_audit_log': action_audit_log,
                          'unix_socket_path': CANARY_SOCKET_PATH} if service is not None else {}
        bind_options = {} if service is not None else {'host': arguments.bind, 'port': arguments.port}
        if arguments.audit_log is not None:
            audit_log = AuditLog.open(arguments.audit_log, minimum_interval=arguments.audit_min_interval or 60)
            server = create_server(reader, allowed_hosts=allowed_hosts, audit_log=audit_log, **bind_options, **canary_options)
        else:
            server = create_server(reader, allowed_hosts=allowed_hosts, **bind_options, **canary_options)
    except (OSError, ValueError) as error:
        if audit_log is not None:
            audit_log.close()
        if action_audit_log is not None:
            action_audit_log.close()
        parser.error(str(error))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if audit_log is not None:
            audit_log.close()
        if action_audit_log is not None:
            action_audit_log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
