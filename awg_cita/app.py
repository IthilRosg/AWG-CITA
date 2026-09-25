"""Loopback-only, read-only HTTP surface for AWG CITA."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import queue
import re
import secrets
import signal
import socket
import socketserver
import stat
import subprocess
import threading
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .audit import ActionAuditLog, AuditLog
from .history import SnapshotHistory
from .lifecycle import LifecycleError, LifecycleService
from .snapshot import AwgDumpError, build_snapshot
from .ui import INDEX_HTML

_STATIC_DIR = Path(__file__).with_name("static")
_STATIC_ASSETS = {
    "/static/sector-console.css": ("text/css; charset=utf-8", _STATIC_DIR.joinpath("sector-console.css").read_bytes()),
    "/static/sector-console.js": ("application/javascript; charset=utf-8", _STATIC_DIR.joinpath("sector-console.js").read_bytes()),
    "/static/sector-console.svg": ("image/svg+xml", _STATIC_DIR.joinpath("sector-console.svg").read_bytes()),
}

_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
_DEFAULT_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_BRACKETED_HOST_RE = re.compile(r"^\[([0-9A-Fa-f:.]+)\](?::([0-9]{1,5}))?$")
_PLAIN_HOST_RE = re.compile(r"^([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?$")
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_CANARY_ROUTE_RE = re.compile(r"^/api/clients/(peer-[0-9a-f]{16})/(disable|enable|delete)$")
_CANARY_CONFIG_RE = re.compile(r"^/api/clients/(peer-[0-9a-f]{16})/config$")
_PROFILE_CLIENTS_RE = re.compile(r"^/api/profiles/(awg3|awg2|wg)/clients$")
_PROFILE_ACTION_RE = re.compile(r"^/api/profiles/(awg3|awg2|wg)/clients/(peer-[0-9a-f]{16})/(disable|enable|delete)$")
_PROFILE_CONFIG_RE = re.compile(r"^/api/profiles/(awg3|awg2|wg)/clients/(peer-[0-9a-f]{16})/config$")
_PROFILE_TEMPLATE_RE = re.compile(r"^/api/profiles/(awg3|awg2|wg)/template$")
_PROFILE_SERVER_RE = re.compile(r"^/api/profiles/(awg3|awg2|wg)/server$")
_OPERATOR_ID_RE = re.compile(r"[A-Za-z0-9_.@-]{1,64}\Z")
MAX_AWG_DUMP_BYTES = 1_048_576
SNAPSHOT_CACHE_TTL_SECONDS = 2.0
TERMINATION_DRAIN_SECONDS = 1
CANARY_SOCKET_PATH = '/run/awg-cita-app/backend.sock'
class AwgOutputTooLarge(RuntimeError):
    """Raised when AWG stdout exceeds the fixed in-memory safety bound."""


class AwgCommandOutputError(RuntimeError):
    """Raised when AWG stdout is not valid UTF-8 telemetry text."""


def _valid_allowed_host(value: str) -> bool:
    if not isinstance(value, str) or not value or value != value.lower():
        return False
    try:
        return str(ipaddress.ip_address(value)) == value
    except ValueError:
        labels = value.split(".")
        return len(value) <= 253 and not all(label.isdigit() for label in labels) and all(_DNS_LABEL_RE.fullmatch(label) for label in labels)


class AwgReader:
    """Read one local AWG dump and return a browser-safe snapshot."""

    def __init__(self, *, binary: str, interface: str, runner: Callable[[tuple[str, ...], int], tuple[str, str]] | None = None, clock: Callable[[], float] | None = None) -> None:
        if not binary.startswith("/"):
            raise ValueError("AWG binary must be an absolute path")
        if not _INTERFACE_RE.fullmatch(interface):
            raise ValueError("invalid AWG interface")
        self.binary = binary
        self.interface = interface
        self.runner = runner or self._run
        self.clock = clock or time.time

    @staticmethod
    def _run(argv: tuple[str, ...], timeout: int, input_data: bytes | None = None) -> tuple[str, str]:
        if input_data is not None and (not isinstance(input_data, bytes) or not 1 <= len(input_data) <= 1024):
            raise ValueError('invalid fixed helper input')
        process = subprocess.Popen(list(argv), stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name == "posix",
                                   env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"})
        results: queue.Queue[tuple[str, bytes]] = queue.Queue()

        def drain(name: str, stream: object) -> None:
            try:
                results.put((name, stream.read(MAX_AWG_DUMP_BYTES + 1)))
            finally:
                stream.close()

        streams = (("stdout", process.stdout), ("stderr", process.stderr))
        threads = [threading.Thread(target=drain, args=(name, stream), daemon=True) for name, stream in streams]
        for thread in threads:
            thread.start()
        if input_data is not None:
            def send_input() -> None:
                try:
                    process.stdin.write(input_data)
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    process.stdin.close()
            threading.Thread(target=send_input, daemon=True).start()
        output: dict[str, bytes] = {}
        deadline = time.monotonic() + timeout
        killed = False
        timed_out = False
        termination_deadline: float | None = None

        def terminate() -> None:
            nonlocal killed, termination_deadline
            if killed:
                return
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                else:
                    killed = True
                    termination_deadline = time.monotonic() + TERMINATION_DRAIN_SECONDS
                    return
            process.kill()
            killed = True
            termination_deadline = time.monotonic() + TERMINATION_DRAIN_SECONDS

        while len(output) < 2:
            try:
                wait = max(0, (termination_deadline if killed else deadline) - time.monotonic())
                name, data = results.get(timeout=wait)
            except queue.Empty:
                if killed:
                    break
                terminate()
                timed_out = True
                continue
            output[name] = data
            if name == "stdout" and len(data) > MAX_AWG_DUMP_BYTES and not killed:
                terminate()
        if not killed:
            for thread in threads:
                thread.join()
        returncode = process.wait(timeout=TERMINATION_DRAIN_SECONDS) if killed else process.wait()
        if len(output.get("stdout", b"")) > MAX_AWG_DUMP_BYTES:
            raise AwgOutputTooLarge("AWG stdout exceeds safety limit")
        if timed_out:
            raise subprocess.TimeoutExpired(argv, timeout)
        if returncode != 0:
            raise RuntimeError("awg command failed")
        if len(output) != 2:
            raise RuntimeError("AWG output streams did not close after termination")
        try:
            stdout = output["stdout"].decode("utf-8")
        except UnicodeDecodeError as error:
            raise AwgCommandOutputError("AWG stdout is not valid UTF-8") from error
        return stdout, output["stderr"].decode("utf-8", errors="replace")

    def snapshot(self) -> dict[str, object]:
        checked_at = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            raw, _stderr = self.runner((self.binary, "show", self.interface, "dump"), 5)
            if len(raw.encode("utf-8")) > MAX_AWG_DUMP_BYTES:
                return {"schema_version": 1, "state": "ERROR", "error_code": "awg_output_too_large", "interface": self.interface, "checked_at": checked_at}
            snapshot = build_snapshot(raw, now=int(self.clock()), interface=self.interface)
            snapshot.update({"state": "OK", "checked_at": checked_at})
            return snapshot
        except AwgDumpError:
            return {"schema_version": 1, "state": "ERROR", "error_code": "invalid_awg_dump", "interface": self.interface, "checked_at": checked_at}
        except AwgOutputTooLarge:
            return {"schema_version": 1, "state": "ERROR", "error_code": "awg_output_too_large", "interface": self.interface, "checked_at": checked_at}
        except (OSError, RuntimeError, subprocess.SubprocessError, TimeoutError):
            return {"schema_version": 1, "state": "ERROR", "error_code": "awg_command_failed", "interface": self.interface, "checked_at": checked_at}


class _SnapshotFlight:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: dict[str, object] | None = None


class SnapshotCollector:
    """Serialize one AWG collection and briefly cache safe successful results."""

    def __init__(self, reader: AwgReader, *, ttl_seconds: float = SNAPSHOT_CACHE_TTL_SECONDS, monotonic: Callable[[], float] | None = None) -> None:
        if ttl_seconds <= 0:
            raise ValueError("snapshot TTL must be positive")
        self._reader = reader
        self._ttl_seconds = float(ttl_seconds)
        self._monotonic = monotonic or time.monotonic
        self._condition = threading.Condition()
        self._cached: tuple[float, dict[str, object]] | None = None
        self._inflight: _SnapshotFlight | None = None

    def _command_failed(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "state": "ERROR",
            "error_code": "awg_command_failed",
            "interface": self._reader.interface,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }

    def _finish(self, flight: _SnapshotFlight, result: dict[str, object]) -> None:
        with self._condition:
            if result.get("state") == "OK":
                self._cached = (self._monotonic(), result)
            else:
                self._cached = None
            flight.result = result
            if self._inflight is flight:
                self._inflight = None
            flight.done.set()

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            now = self._monotonic()
            if self._cached is not None:
                cached_at, cached = self._cached
                if 0 <= now - cached_at < self._ttl_seconds:
                    return deepcopy(cached)
            flight = self._inflight
            if flight is None:
                flight = _SnapshotFlight()
                self._inflight = flight
                owner = True
            else:
                owner = False

        if not owner:
            flight.done.wait()
            if flight.result is None:
                return self._command_failed()
            return deepcopy(flight.result)

        try:
            try:
                result = self._reader.snapshot()
            except Exception:
                result = self._command_failed()
            result = deepcopy(result)
            self._finish(flight, result)
            return deepcopy(result)
        except BaseException:
            self._finish(flight, self._command_failed())
            raise


def _template_request(profile: str, value: dict[str, object] | None = None) -> dict[str, object]:
    from .client_templates import validate
    if profile not in {'awg3', 'awg2', 'wg'}:
        raise ValueError('invalid profile')
    if value is not None:
        value = validate(value)
    argv = ('/usr/bin/sudo', '-n', '--', '/usr/local/sbin/awg-cita-template', profile,
            'show' if value is None else 'update')
    try:
        raw, err = AwgReader._run(argv, 10, None if value is None else json.dumps(value, separators=(',', ':')).encode('ascii'))
        if err or len(raw) > 2048:
            raise ValueError('template helper failed')
        result = json.loads(raw)
        if (not isinstance(result, dict) or set(result) != {'schema_version', 'profile', 'template'} or
            result['schema_version'] != 1 or result['profile'] != profile or
            validate(result['template']) != result['template']):
            raise ValueError('invalid template helper response')
        return result
    except Exception:
        raise LifecycleError('awg_command_failed') from None


class _Handler(BaseHTTPRequestHandler):
    reader: AwgReader
    collector: SnapshotCollector
    allowed_hosts: frozenset[str]
    history: SnapshotHistory
    audit_log: AuditLog | None
    action_audit_log: ActionAuditLog | None
    require_operator_header: bool
    test_mode: bool
    lifecycle_service: LifecycleService | None
    profile_services: dict[str, LifecycleService]
    operator_origin: str | None
    operator_id: str | None
    sessions: dict[str, tuple[str, float, str]]
    sessions_lock: threading.Lock

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _headers(self, status: int, content_type: str, length: int, allow: str | None = None, cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        if allow:
            self.send_header("Allow", allow)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _json(self, status: int, payload: dict[str, object], include_body: bool = True) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self._headers(status, "application/json; charset=utf-8", len(body))
        if include_body:
            self.wfile.write(body)

    def _index_html(self, csrf: str | None = None) -> bytes:
        body = INDEX_HTML.encode()
        if csrf is not None:
            body = body.replace(b'data-runtime="mock_lifecycle"', b'data-runtime="real_canary"', 1)
            return body.replace(b'</head>', b'<meta name="csrf-token" content="' + csrf.encode('ascii') + b'">\n</head>', 1)
        if not self.test_mode:
            return body
        shell = b'<div class="shell" data-runtime="mock_lifecycle">'
        replacement = b'<div class="shell" data-runtime="mock_lifecycle" data-test-mode="true">'
        return body.replace(shell, replacement, 1)

    def _operator_actor(self) -> str | None:
        values = self.headers.get_all('X-AWG-Operator')
        expected = self.operator_id or ('test-operator' if self.test_mode else None)
        if values is None and self.test_mode and not self.require_operator_header:
            return expected
        if values != [expected] or expected is None or not _OPERATOR_ID_RE.fullmatch(expected):
            return None
        return expected

    def _new_session(self, actor: str) -> tuple[str, str]:
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.sessions_lock:
            now = time.monotonic()
            for key, (_token, created, _actor) in list(self.sessions.items()):
                if now - created >= 3600:
                    del self.sessions[key]
            if len(self.sessions) >= 128:
                self.sessions.pop(next(iter(self.sessions)))
            self.sessions[sid] = (csrf, now, actor)
        return sid, csrf

    def _session_token(self) -> str | None:
        actor = self._operator_actor()
        if actor is None:
            return None
        cookies = self.headers.get_all('Cookie')
        if cookies is None or len(cookies) != 1:
            return None
        values = [part.strip().split('=', 1)[1] for part in cookies[0].split(';') if part.strip().startswith('awg_cita_session=')]
        if len(values) != 1:
            return None
        with self.sessions_lock:
            item = self.sessions.get(values[0])
            if item is None or time.monotonic() - item[1] >= 3600 or item[2] != actor:
                return None
            return item[0]

    @staticmethod
    def _lifecycle_status(error: LifecycleError) -> int:
        return {'invalid_request': 400, 'client_not_found': 404, 'invalid_state': 409, 'conflict': 409}.get(error.code, 503)

    def _host_allowed(self) -> bool:
        values = self.headers.get_all("Host")
        if values is None or len(values) != 1:
            return False
        value = values[0].strip().lower()
        match = _BRACKETED_HOST_RE.fullmatch(value) if value.startswith("[") else _PLAIN_HOST_RE.fullmatch(value)
        if not match:
            return False
        host, port = match.groups()
        if value.startswith("["):
            try:
                ipaddress.IPv6Address(host)
            except ipaddress.AddressValueError:
                return False
        if port and not 1 <= int(port) <= 65535:
            return False
        return host in self.allowed_hosts

    def _reject_untrusted_host(self) -> bool:
        if self._host_allowed():
            return False
        self._json(421, {"error_code": "untrusted_host"})
        return True

    def _empty(self, status: int, allow: str | None = None) -> None:
        self._headers(status, "text/plain; charset=utf-8", 0, allow=allow)

    def _asset(self, path: str, include_body: bool = True) -> bool:
        asset = _STATIC_ASSETS.get(path)
        if asset is None:
            return False
        content_type, body = asset
        self._headers(200, content_type, len(body))
        if include_body:
            self.wfile.write(body)
        return True

    def _status(self, include_body: bool = True) -> None:
        if self.audit_log is not None:
            try:
                self.audit_log.preflight()
            except Exception:
                self._json(503, {"schema_version": 1, "state": "ERROR", "error_code": "audit_write_failed", "checked_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}, include_body=include_body)
                return
        data = self.collector.snapshot()
        if self.audit_log is not None:
            try:
                self.audit_log.record(data)
            except Exception:
                self._json(503, {"schema_version": 1, "state": "ERROR", "error_code": "audit_write_failed", "checked_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}, include_body=include_body)
                return
        self.history.record(data)
        self._json(200 if data.get("state") == "OK" else 503, data, include_body=include_body)

    def do_GET(self) -> None:
        if self._reject_untrusted_host():
            return
        path = urlsplit(self.path).path
        if path == "/":
            cookie = None
            if self.lifecycle_service is not None:
                actor = self._operator_actor()
                if actor is None:
                    self._json(401, {'error_code': 'unauthorized'})
                    return
                sid, csrf = self._new_session(actor)
                body = self._index_html(csrf)
                cookie = 'awg_cita_session=' + sid + '; HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if self.operator_origin.startswith('https://') else '')
            else:
                body = self._index_html()
            self._headers(200, "text/html; charset=utf-8", len(body), cookie=cookie)
            self.wfile.write(body)
            return
        if self._asset(path):
            return
        if path == "/api/history":
            self._json(200, {"schema_version": 1, "history": self.history.records()})
            return
        template_match = _PROFILE_TEMPLATE_RE.fullmatch(self.path)
        if template_match is not None and self.lifecycle_service is not None:
            if self._session_token() is None:
                self._json(401, {'error_code': 'unauthorized'})
                return
            try:
                self._json(200, _template_request(template_match.group(1)))
            except LifecycleError as error:
                self._json(self._lifecycle_status(error), {'error_code': error.code})
            return
        server_match = _PROFILE_SERVER_RE.fullmatch(self.path)
        if server_match is not None and self.profile_services.get(server_match.group(1)) is not None:
            if self._session_token() is None:
                self._json(401, {'error_code': 'unauthorized'})
                return
            try:
                self._json(200, self.profile_services[server_match.group(1)].server_settings())
            except LifecycleError as error:
                self._json(self._lifecycle_status(error), {'error_code': error.code})
            return
        profile_list = _PROFILE_CLIENTS_RE.fullmatch(self.path)
        list_service = self.profile_services.get(profile_list.group(1)) if profile_list else self.lifecycle_service if self.path == '/api/clients' else None
        if list_service is not None:
            if self._session_token() is None:
                self._json(401, {'error_code': 'unauthorized'})
                return
            try:
                self._json(200, {'schema_version': 1, 'clients': list_service.list_clients()})
            except LifecycleError as error:
                self._json(self._lifecycle_status(error), {'error_code': error.code})
            return
        profile_config = _PROFILE_CONFIG_RE.fullmatch(self.path)
        config_match = _CANARY_CONFIG_RE.fullmatch(self.path)
        config_service = self.profile_services.get(profile_config.group(1)) if profile_config else self.lifecycle_service if config_match else None
        if config_service is not None:
            if self._session_token() is None:
                self._json(401, {'error_code': 'unauthorized'})
                return
            try:
                self._json(200, config_service.get_configuration(profile_config.group(2) if profile_config else config_match.group(1)))
            except LifecycleError as error:
                self._json(self._lifecycle_status(error), {'error_code': error.code})
            return
        if path != "/api/status":
            self._json(404, {"error_code": "not_found"})
            return
        self._status()

    def do_HEAD(self) -> None:
        if self._reject_untrusted_host():
            return
        path = urlsplit(self.path).path
        if path == "/":
            body = self._index_html()
            self._headers(200, "text/html; charset=utf-8", len(body))
        elif self._asset(path, include_body=False):
            return
        elif path == "/api/history":
            self._json(200, {"schema_version": 1, "history": self.history.records()}, include_body=False)
        elif path == "/api/status":
            self._status(include_body=False)
        else:
            self._json(404, {"error_code": "not_found"}, include_body=False)

    def do_OPTIONS(self) -> None:
        if self._reject_untrusted_host():
            return
        path = urlsplit(self.path).path
        if path in {"/api/status", "/api/history"}:
            self._empty(204, allow="GET, HEAD, OPTIONS")
        else:
            self._json(404, {"error_code": "not_found"})

    def _method_not_allowed(self) -> None:
        if self._reject_untrusted_host():
            return
        self._empty(405, allow="GET, HEAD, OPTIONS")

    def do_POST(self) -> None:
        if self._reject_untrusted_host():
            return
        if self.lifecycle_service is None:
            self._method_not_allowed()
            return
        path = self.path
        profile_match = _PROFILE_ACTION_RE.fullmatch(path)
        profile_list = _PROFILE_CLIENTS_RE.fullmatch(path)
        template_match = _PROFILE_TEMPLATE_RE.fullmatch(path)
        profile_config = _PROFILE_CONFIG_RE.fullmatch(path)
        canary_config = _CANARY_CONFIG_RE.fullmatch(path)
        match = _CANARY_ROUTE_RE.fullmatch(path)
        create = path == '/api/clients' or profile_list is not None
        service = (self.profile_services.get(profile_match.group(1)) if profile_match else
                   self.profile_services.get(profile_list.group(1)) if profile_list else
                   self.profile_services.get(profile_config.group(1)) if profile_config else self.lifecycle_service)
        if (match is None and profile_match is None and not create and template_match is None and
                profile_config is None and canary_config is None) or service is None:
            self._json(404, {'error_code': 'not_found'})
            return
        kinds = self.headers.get_all('Content-Type')
        lengths = self.headers.get_all('Content-Length')
        if kinds != ['application/json']:
            self._json(415, {'error_code': 'unsupported_media_type'})
            return
        if (lengths is None or len(lengths) != 1 or not lengths[0].isdigit() or
                not 1 <= int(lengths[0]) <= 2048 or self.headers.get('Transfer-Encoding')):
            self._json(400, {'error_code': 'invalid_request'})
            return
        try:
            self.connection.settimeout(10)
            body = self.rfile.read(int(lengths[0]))
        except (OSError, TimeoutError):
            body = b''
        if len(body) != int(lengths[0]):
            self.close_connection = True
            self._json(400, {'error_code': 'invalid_request'})
            return
        # The relay has already bounded and forwarded this body. Consume it before
        # an auth rejection so the Unix backend cannot close during proxy send().
        csrf = self._session_token()
        if csrf is None:
            self._json(401, {'error_code': 'unauthorized'})
            return
        origin = self.headers.get_all('Origin')
        tokens = self.headers.get_all('X-CSRF-Token')
        if (origin != [self.operator_origin] or tokens is None or len(tokens) != 1 or
                not secrets.compare_digest(tokens[0], csrf) or
                self.headers.get('Sec-Fetch-Site', 'same-origin') != 'same-origin'):
            self._json(403, {'error_code': 'forbidden'})
            return
        def unique_pairs(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('duplicate request field')
                value[key] = item
            return value

        try:
            payload = json.loads(body, object_pairs_hook=unique_pairs)
            operation = ('template' if template_match else 'create' if create else 'config_update' if profile_config or canary_config else
                         profile_match.group(3) if profile_match else match.group(2))
            client_id = ('' if create or template_match else profile_config.group(2) if profile_config else
                         canary_config.group(1) if canary_config else profile_match.group(2) if profile_match else match.group(1))
            keys = ({'dns_server', 'allowed_ips', 'mtu', 'keepalive', 'idempotencyKey'} if template_match else
                    {'name', 'tags', 'idempotencyKey', 'acknowledged'} if create else
                    {'dns_server', 'allowed_ips', 'mtu', 'keepalive', 'expectedRevision', 'idempotencyKey'} if operation == 'config_update' else
                    {'disable': {'idempotencyKey', 'reason'}, 'enable': {'idempotencyKey'},
                     'delete': {'idempotencyKey', 'confirmation'}}[operation])
            if not isinstance(payload, dict) or set(payload) != keys or not isinstance(payload['idempotencyKey'], str):
                raise LifecycleError('invalid_request')
            if template_match:
                from .client_templates import validate
                validate({key: payload[key] for key in ('dns_server', 'allowed_ips', 'mtu', 'keepalive')})
            if operation == 'config_update':
                from .client_config_edit import validate_revision
                from .client_templates import validate
                validate_revision(payload['expectedRevision'])
                validate({key: payload[key] for key in ('dns_server', 'allowed_ips', 'mtu', 'keepalive')})
        except (ValueError, UnicodeError, LifecycleError):
            self._json(400, {'error_code': 'invalid_request'})
            return

        actor = self._operator_actor()
        correlation_id = secrets.token_hex(16)
        nonce_digest = hashlib.sha256(payload['idempotencyKey'].encode('utf-8')).hexdigest()
        audit_profile = (template_match.group(1) if template_match else profile_config.group(1) if profile_config else profile_match.group(1) if profile_match else
                         profile_list.group(1) if profile_list else 'awg3')
        audit_operation = audit_profile + '_' + operation if template_match or audit_profile != 'awg3' else operation
        if self.action_audit_log is not None:
            try:
                self.action_audit_log.record_action(phase='INTENT', correlation_id=correlation_id,
                                                    actor=actor, operation=audit_operation, client_id=client_id,
                                                    nonce_digest=nonce_digest)
            except Exception:
                self._json(503, {'error_code': 'audit_write_failed'})
                return
        try:
            if template_match:
                result = _template_request(template_match.group(1),
                                           {key: payload[key] for key in ('dns_server', 'allowed_ips', 'mtu', 'keepalive')})
            elif operation == 'config_update':
                result = service.update_configuration(client_id, payload['expectedRevision'],
                                                      {key: payload[key] for key in ('dns_server', 'allowed_ips', 'mtu', 'keepalive')},
                                                      payload['idempotencyKey'])
            elif create:
                result = service.create_client(payload['name'], payload['tags'],
                                                              payload['idempotencyKey'], payload['acknowledged'])
                client_id = result['client']['id']
            elif operation == 'disable':
                result = {'schema_version': 1, 'client': service.disable_client(client_id, payload['idempotencyKey'], payload['reason'])}
            elif operation == 'enable':
                result = {'schema_version': 1, 'client': service.enable_client(client_id, payload['idempotencyKey'])}
            else:
                result = service.delete_client(client_id, payload['idempotencyKey'], payload['confirmation'])
            status, response, outcome = 200, result, 'OK'
        except LifecycleError as error:
            status, response, outcome = self._lifecycle_status(error), {'error_code': error.code}, error.code
        except Exception:
            status, response, outcome = 503, {'error_code': 'awg_command_failed'}, 'awg_command_failed'
        if self.action_audit_log is not None:
            try:
                self.action_audit_log.record_action(phase='RESULT', correlation_id=correlation_id,
                                                    actor=actor, operation=audit_operation, client_id=client_id,
                                                    nonce_digest=nonce_digest, result=outcome)
            except Exception:
                self._json(503, {'error_code': 'audit_write_failed'})
                return
        self._json(status, response)

    do_PUT = do_PATCH = do_DELETE = _method_not_allowed


class _PrivateUnixHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_UNIX if hasattr(socket, 'AF_UNIX') else socket.AF_INET

    def __init__(self, path: str, handler: type[_Handler], *, test_mode: bool) -> None:
        self._bound_inode: tuple[int, int] | None = None
        self._test_mode = test_mode
        super().__init__(path, handler)

    def server_bind(self) -> None:
        path = self.server_address
        parent = os.lstat(os.path.dirname(path))
        if not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) != 0o700:
            raise ValueError('canary socket parent must be a private directory (0700)')
        if os.name == 'posix':
            if parent.st_uid != os.geteuid():
                raise ValueError('canary socket parent must belong to the service user')
            if not self._test_mode:
                import pwd
                if pwd.getpwuid(os.geteuid()).pw_name != 'awg-manager':
                    raise ValueError('canary actions must run as awg-manager')
        elif not self._test_mode:
            raise ValueError('canary Unix ingress requires POSIX ownership semantics')
        if os.path.lexists(path):
            raise ValueError('canary socket path already exists; refusing to replace it')
        try:
            socketserver.TCPServer.server_bind(self)
            created = os.lstat(path)
            if not stat.S_ISSOCK(created.st_mode):
                raise ValueError('canary socket bind did not create a socket')
            self._bound_inode = (created.st_dev, created.st_ino)
            os.chmod(path, 0o600)
            metadata = os.lstat(path)
            if not stat.S_ISSOCK(metadata.st_mode) or (os.name == 'posix' and
                    (metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600)) or (
                    metadata.st_dev, metadata.st_ino) != self._bound_inode:
                raise ValueError('canary socket metadata is unsafe')
            self.server_name = 'localhost'
            self.server_port = 0
        except BaseException:
            self.server_close()
            raise

    def server_close(self) -> None:
        super().server_close()
        if self._bound_inode is not None:
            try:
                metadata = os.lstat(self.server_address)
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISSOCK(metadata.st_mode) and (metadata.st_dev, metadata.st_ino) == self._bound_inode:
                    os.unlink(self.server_address)
            self._bound_inode = None


def create_server(
    reader: AwgReader,
    host: str = "127.0.0.1",
    port: int = 8788,
    allowed_hosts: frozenset[str] | None = None,
    audit_log: AuditLog | None = None,
    *,
    test_mode: bool = False,
    lifecycle_service: LifecycleService | None = None,
    profile_services: dict[str, LifecycleService] | None = None,
    operator_origin: str | None = None,
    unix_socket_path: str | None = None,
    operator_id: str | None = None,
    action_audit_log: ActionAuditLog | None = None,
    require_operator_header: bool = False,
) -> ThreadingHTTPServer:
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("AWG CITA must bind to a loopback address")
    if profile_services is not None and (lifecycle_service is None or
                                         not isinstance(profile_services, dict) or
                                         not set(profile_services) <= {'awg3', 'awg2', 'wg'} or
                                         any(not isinstance(item, LifecycleService) for item in profile_services.values()) or
                                         profile_services.get('awg3') not in (None, lifecycle_service)):
        raise ValueError('invalid profile services')
    if allowed_hosts is not None and not all(_valid_allowed_host(value) for value in allowed_hosts):
        raise ValueError("allowed_hosts must contain canonical hostnames or IP addresses")
    if lifecycle_service is not None and (not operator_origin or urlsplit(operator_origin).scheme not in {'http', 'https'} or
                                          urlsplit(operator_origin).hostname not in (allowed_hosts or _DEFAULT_ALLOWED_HOSTS)):
        raise ValueError('canary actions require an explicit allowed operator origin')
    if unix_socket_path is not None and lifecycle_service is None:
        raise ValueError('Unix ingress requires canary actions')
    if lifecycle_service is not None and unix_socket_path is None and not test_mode:
        raise ValueError('canary actions require private Unix ingress')
    if lifecycle_service is not None and not test_mode and (
            operator_id is None or not _OPERATOR_ID_RE.fullmatch(operator_id) or action_audit_log is None):
        raise ValueError('canary actions require operator identity and action audit')
    if unix_socket_path is not None and not test_mode and unix_socket_path != CANARY_SOCKET_PATH:
        raise ValueError('canary actions require the fixed private Unix socket')

    class Handler(_Handler):
        pass

    Handler.reader = reader
    Handler.collector = SnapshotCollector(reader)
    Handler.allowed_hosts = _DEFAULT_ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts
    Handler.history = SnapshotHistory()
    Handler.audit_log = audit_log
    Handler.action_audit_log = action_audit_log
    Handler.require_operator_header = require_operator_header or not test_mode
    Handler.test_mode = test_mode
    Handler.lifecycle_service = lifecycle_service
    Handler.profile_services = {'awg3': lifecycle_service, **(profile_services or {})} if lifecycle_service is not None else {}
    Handler.operator_origin = operator_origin
    Handler.operator_id = operator_id
    Handler.sessions = {}
    Handler.sessions_lock = threading.Lock()
    if unix_socket_path is not None:
        if not hasattr(socket, 'AF_UNIX'):
            raise ValueError('Unix sockets unavailable')
        return _PrivateUnixHTTPServer(unix_socket_path, Handler, test_mode=test_mode)
    if host == "::1":
        class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
            address_family = socket.AF_INET6

        return IPv6ThreadingHTTPServer((host, port), Handler)
    return ThreadingHTTPServer((host, port), Handler)
