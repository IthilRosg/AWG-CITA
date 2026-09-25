"""Safe projection helpers for optional local audit evidence."""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import time
import datetime as dt
from pathlib import Path
from typing import Callable

_SUMMARY_KEYS = ("total", "online", "stale", "offline", "never", "unknown", "rx_bytes", "tx_bytes")
_COUNT_KEYS = ("total", "online", "stale", "offline", "never", "unknown")
_MAX_COUNT = 2_147_483_647
_MAX_BYTES = 18_446_744_073_709_551_615
_ERROR_CODES = frozenset({"awg_output_too_large", "invalid_awg_dump", "awg_command_failed"})
_MAX_AUDIT_BYTES = 1_048_576
_MAX_RECORD_BYTES = 512
_ACTION_OPERATIONS = frozenset({"create", "enable", "disable", "delete"})
_ACTION_RESULTS = frozenset({"OK", "invalid_request", "client_not_found", "invalid_state", "conflict",
                             "internal_error", "awg_timeout", "configuration_failed", "awg_command_failed"})
_ACTOR_RE = re.compile(r"[A-Za-z0-9_.@-]{1,64}\Z")
_PEER_RE = re.compile(r"peer-[0-9a-f]{16}\Z")
_HEX32_RE = re.compile(r"[0-9a-f]{32}\Z")
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _checked_at(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid audit timestamp")
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S+00:00")
    except ValueError as error:
        raise ValueError("invalid audit timestamp") from error
    return value


def _integer(value: object, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError("invalid audit counter")
    return value


def project_status_event(snapshot: dict[str, object], *, checked_at: str) -> dict[str, object]:
    """Construct the fixed safe evidence shape for one sanitized snapshot."""
    checked_at = _checked_at(checked_at)
    if snapshot.get("state") == "ERROR":
        error_code = snapshot.get("error_code")
        if error_code not in _ERROR_CODES:
            raise ValueError("invalid audit error code")
        return {
            "schema_version": 1,
            "kind": "status",
            "checked_at": checked_at,
            "state": "ERROR",
            "error_code": error_code,
        }
    if snapshot.get("state") != "OK":
        raise ValueError("invalid audit state")
    summary = snapshot["summary"]
    if not isinstance(summary, dict):
        raise ValueError("invalid audit summary")
    peer_count = _integer(snapshot["peer_count"], _MAX_COUNT)
    safe_summary = {
        key: _integer(summary[key], _MAX_COUNT if key in _COUNT_KEYS else _MAX_BYTES)
        for key in _SUMMARY_KEYS
    }
    if peer_count != safe_summary["total"] or safe_summary["total"] != sum(safe_summary[key] for key in _COUNT_KEYS[1:]):
        raise ValueError("inconsistent audit summary")
    return {
        "schema_version": 1,
        "kind": "status",
        "checked_at": checked_at,
        "state": "OK",
        "peer_count": peer_count,
        "summary": safe_summary,
    }


def project_action_event(*, checked_at: str, phase: str, correlation_id: str,
                         actor: str, operation: str, client_id: str,
                         nonce_digest: str, result: str | None = None) -> dict[str, object]:
    checked_at = _checked_at(checked_at)
    if (phase not in {"INTENT", "RESULT"} or not _HEX32_RE.fullmatch(correlation_id) or
            not _ACTOR_RE.fullmatch(actor) or operation not in _ACTION_OPERATIONS or
            not isinstance(client_id, str) or (client_id and not _PEER_RE.fullmatch(client_id)) or
            not _HEX64_RE.fullmatch(nonce_digest) or
            (phase == "INTENT" and result is not None) or
            (phase == "RESULT" and result not in _ACTION_RESULTS)):
        raise ValueError("invalid action audit event")
    return {"schema_version": 1, "kind": "action", "checked_at": checked_at,
            "phase": phase, "correlation_id": correlation_id, "actor": actor,
            "operation": operation, "client_id": client_id,
            "nonce_digest": nonce_digest, **({"result": result} if result is not None else {})}


class AuditLog:
    """One optional POSIX-local append-only safe evidence file."""

    def __init__(self, descriptor: int, parent_descriptor: int, leaf_name: str, *, minimum_interval: int, clock: Callable[[], str], monotonic: Callable[[], float], device: int, inode: int, expected_size: int) -> None:
        self._descriptor = descriptor
        self._parent_descriptor = parent_descriptor
        self._leaf_name = leaf_name
        self._minimum_interval = minimum_interval
        self._clock = clock
        self._monotonic = monotonic
        self._device = device
        self._inode = inode
        self._expected_size = expected_size
        self._lock = threading.Lock()
        self._last_recorded: float | None = None
        self._failed = False

    @classmethod
    def open(cls, path: Path, *, minimum_interval: int, clock: Callable[[], str] | None = None, monotonic: Callable[[], float] | None = None) -> "AuditLog":
        if os.name != "posix":
            raise ValueError("audit evidence requires POSIX")
        if isinstance(minimum_interval, bool) or not isinstance(minimum_interval, int) or not 60 <= minimum_interval <= 3600:
            raise ValueError("audit interval must be between 60 and 3600 seconds")
        if not path.is_absolute() or path.name in {"", ".", ".."}:
            raise ValueError("audit path must be absolute")
        parent_fd = cls._open_parent(path.parent)
        descriptor: int | None = None
        try:
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
            metadata = cls._validate_descriptor(descriptor)
            size = metadata.st_size
            reader = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
            try:
                reader_metadata = cls._validate_descriptor(reader)
                if reader_metadata.st_dev != metadata.st_dev or reader_metadata.st_ino != metadata.st_ino:
                    raise ValueError("audit file changed during open")
                trailing_byte = os.pread(reader, 1, size - 1) if size else b""
            finally:
                os.close(reader)
            if size > _MAX_AUDIT_BYTES or (size and trailing_byte != b"\n"):
                raise ValueError("invalid audit file")
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_fd)
            raise
        return cls(descriptor, parent_fd, path.name, minimum_interval=minimum_interval, clock=clock or _utc_now, monotonic=monotonic or time.monotonic, device=metadata.st_dev, inode=metadata.st_ino, expected_size=size)

    @staticmethod
    def _open_parent(path: Path) -> int:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for component in path.parts[1:]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    @staticmethod
    def _validate_descriptor(descriptor: int) -> os.stat_result:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_nlink != 1 or metadata.st_mode & 0o077:
            raise ValueError("unsafe audit file")
        return metadata

    def _validate_current_descriptor(self, expected_size: int | None = None) -> None:
        metadata = self._validate_descriptor(self._descriptor)
        leaf_metadata = os.stat(self._leaf_name, dir_fd=self._parent_descriptor, follow_symlinks=False)
        if expected_size is None:
            expected_size = self._expected_size
        if metadata.st_dev != self._device or metadata.st_ino != self._inode or metadata.st_size != expected_size or leaf_metadata.st_dev != self._device or leaf_metadata.st_ino != self._inode:
            raise ValueError("audit file changed unexpectedly")

    def preflight(self) -> None:
        with self._lock:
            if self._failed:
                raise RuntimeError("audit writer failed")
            try:
                self._validate_current_descriptor()
            except Exception as error:
                self._failed = True
                raise RuntimeError("audit writer failed") from error

    def record(self, snapshot: dict[str, object]) -> bool:
        with self._lock:
            if self._failed:
                raise RuntimeError("audit writer failed")
            try:
                self._validate_current_descriptor()
                now = self._monotonic()
                if self._last_recorded is not None and now - self._last_recorded < self._minimum_interval:
                    return False
                event = project_status_event(snapshot, checked_at=self._clock())
                self._append_event(event)
            except Exception as error:
                self._failed = True
                raise RuntimeError("audit writer failed") from error
            self._last_recorded = now
            return True

    def _append_event(self, event: dict[str, object]) -> None:
        encoded = (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise ValueError("audit record too large")
        metadata = os.fstat(self._descriptor)
        if metadata.st_size + len(encoded) > _MAX_AUDIT_BYTES:
            raise ValueError("audit file capacity exhausted")
        written = os.write(self._descriptor, encoded)
        if written != len(encoded):
            raise OSError("short audit write")
        os.fsync(self._descriptor)
        new_size = self._expected_size + written
        self._validate_current_descriptor(expected_size=new_size)
        self._expected_size = new_size

    def close(self) -> None:
        with self._lock:
            if self._descriptor is not None:
                os.close(self._descriptor)
                self._descriptor = None
            if self._parent_descriptor is not None:
                os.close(self._parent_descriptor)
                self._parent_descriptor = None


class ActionAuditLog(AuditLog):
    """Durable, fail-closed intent/result evidence for action mode."""

    @classmethod
    def open(cls, path: Path, *, clock: Callable[[], str] | None = None) -> "ActionAuditLog":
        log = super().open(path, minimum_interval=60, clock=clock)
        try:
            reader = os.open(log._leaf_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=log._parent_descriptor)
            try:
                metadata = cls._validate_descriptor(reader)
                if (metadata.st_dev, metadata.st_ino, metadata.st_size) != (
                        log._device, log._inode, log._expected_size):
                    raise ValueError("action audit file changed during open")
                data = os.read(reader, _MAX_AUDIT_BYTES + 1)
            finally:
                os.close(reader)
            if len(data) != log._expected_size:
                raise ValueError("action audit file changed during open")
            pending: dict[str, tuple[str, str, str]] = {}
            completed: set[str] = set()
            for line in data.splitlines():
                event = json.loads(line)
                projected = project_action_event(
                    checked_at=event["checked_at"], phase=event["phase"],
                    correlation_id=event["correlation_id"], actor=event["actor"],
                    operation=event["operation"], client_id=event["client_id"],
                    nonce_digest=event["nonce_digest"], result=event.get("result"))
                if event != projected:
                    raise ValueError("invalid action audit record")
                correlation_id = event["correlation_id"]
                if event["phase"] == "INTENT":
                    if correlation_id in pending or correlation_id in completed:
                        raise ValueError("duplicate action audit intent")
                    pending[correlation_id] = (event["actor"], event["operation"], event["nonce_digest"])
                else:
                    if pending.pop(correlation_id, None) != (
                            event["actor"], event["operation"], event["nonce_digest"]):
                        raise ValueError("unpaired action audit result")
                    completed.add(correlation_id)
            if pending:
                raise ValueError("unmatched action audit intent requires reconciliation")
            log._validate_current_descriptor()
            return log
        except Exception as error:
            log.close()
            if isinstance(error, (OSError, ValueError)):
                raise
            raise ValueError("invalid action audit file") from error

    def record_action(self, *, phase: str, correlation_id: str, actor: str,
                      operation: str, client_id: str, nonce_digest: str,
                      result: str | None = None) -> None:
        with self._lock:
            if self._failed:
                raise RuntimeError("action audit writer failed")
            try:
                self._validate_current_descriptor()
                event = project_action_event(checked_at=self._clock(), phase=phase,
                                             correlation_id=correlation_id, actor=actor,
                                             operation=operation, client_id=client_id,
                                             nonce_digest=nonce_digest, result=result)
                self._append_event(event)
            except Exception as error:
                self._failed = True
                raise RuntimeError("action audit writer failed") from error
