"""Loopback-only, read-only HTTP surface for AWG CITA."""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import os
import queue
import re
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .history import SnapshotHistory
from .snapshot import AwgDumpError, build_snapshot
from .ui import INDEX_HTML

_STATIC_DIR = Path(__file__).with_name("static")
_STATIC_ASSETS = {
    "/static/sector-console.css": ("text/css; charset=utf-8", _STATIC_DIR.joinpath("sector-console.css").read_bytes()),
    "/static/sector-console.js": ("application/javascript; charset=utf-8", _STATIC_DIR.joinpath("sector-console.js").read_bytes()),
}

_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
_DEFAULT_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_BRACKETED_HOST_RE = re.compile(r"^\[([0-9A-Fa-f:.]+)\](?::([0-9]{1,5}))?$")
_PLAIN_HOST_RE = re.compile(r"^([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?$")
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
MAX_AWG_DUMP_BYTES = 1_048_576
TERMINATION_DRAIN_SECONDS = 1


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
    def _run(argv: tuple[str, ...], timeout: int) -> tuple[str, str]:
        process = subprocess.Popen(list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name == "posix", env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"})
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
        except (OSError, RuntimeError, subprocess.SubprocessError, TimeoutError):
            return {"schema_version": 1, "state": "ERROR", "error_code": "awg_command_failed", "interface": self.interface, "checked_at": checked_at}


class _Handler(BaseHTTPRequestHandler):
    reader: AwgReader
    allowed_hosts: frozenset[str]
    history: SnapshotHistory

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _headers(self, status: int, content_type: str, length: int, allow: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        if allow:
            self.send_header("Allow", allow)
        self.end_headers()

    def _json(self, status: int, payload: dict[str, object], include_body: bool = True) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self._headers(status, "application/json; charset=utf-8", len(body))
        if include_body:
            self.wfile.write(body)

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

    def do_GET(self) -> None:
        if self._reject_untrusted_host():
            return
        path = urlsplit(self.path).path
        if path == "/":
            body = INDEX_HTML.encode()
            self._headers(200, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
            return
        if self._asset(path):
            return
        if path == "/api/history":
            self._json(200, {"schema_version": 1, "history": self.history.records()})
            return
        if path != "/api/status":
            self._json(404, {"error_code": "not_found"})
            return
        data = self.reader.snapshot()
        self.history.record(data)
        self._json(200 if data.get("state") == "OK" else 503, data)

    def do_HEAD(self) -> None:
        if self._reject_untrusted_host():
            return
        path = urlsplit(self.path).path
        if path == "/":
            body = INDEX_HTML.encode()
            self._headers(200, "text/html; charset=utf-8", len(body))
        elif self._asset(path, include_body=False):
            return
        elif path == "/api/history":
            self._json(200, {"schema_version": 1, "history": self.history.records()}, include_body=False)
        elif path == "/api/status":
            data = self.reader.snapshot()
            self._json(200 if data.get("state") == "OK" else 503, data, include_body=False)
        else:
            self._json(404, {"error_code": "not_found"}, include_body=False)

    def do_OPTIONS(self) -> None:
        if self._reject_untrusted_host():
            return
        if urlsplit(self.path).path in {"/api/status", "/api/history"}:
            self._empty(204, allow="GET, HEAD, OPTIONS")
        else:
            self._json(404, {"error_code": "not_found"})

    def _method_not_allowed(self) -> None:
        if self._reject_untrusted_host():
            return
        self._empty(405, allow="GET, HEAD, OPTIONS")

    do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed


def create_server(reader: AwgReader, host: str = "127.0.0.1", port: int = 8788, allowed_hosts: frozenset[str] | None = None) -> ThreadingHTTPServer:
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("AWG CITA must bind to a loopback address")
    if allowed_hosts is not None and not all(_valid_allowed_host(value) for value in allowed_hosts):
        raise ValueError("allowed_hosts must contain canonical hostnames or IP addresses")

    class Handler(_Handler):
        pass

    Handler.reader = reader
    Handler.allowed_hosts = _DEFAULT_ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts
    Handler.history = SnapshotHistory()
    if host == "::1":
        class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
            address_family = socket.AF_INET6

        return IPv6ThreadingHTTPServer((host, port), Handler)
    return ThreadingHTTPServer((host, port), Handler)
