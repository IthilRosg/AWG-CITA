"""Safe projection helpers for optional local audit evidence."""

from __future__ import annotations

import json
import os
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
            except Exception as error:
                self._failed = True
                raise RuntimeError("audit writer failed") from error
            self._last_recorded = now
            return True

    def close(self) -> None:
        with self._lock:
            if self._descriptor is not None:
                os.close(self._descriptor)
                self._descriptor = None
            if self._parent_descriptor is not None:
                os.close(self._parent_descriptor)
                self._parent_descriptor = None
