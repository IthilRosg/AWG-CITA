"""Bounded, browser-safe history for already-sanitized AWG snapshots."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Deque

_SUMMARY_KEYS = ("total", "online", "stale", "offline", "never", "unknown", "rx_bytes", "tx_bytes")


class SnapshotHistory:
    """Retain only a bounded safe projection of read-only snapshot outcomes."""

    def __init__(self, limit: int = 60) -> None:
        if limit < 1:
            raise ValueError("history limit must be positive")
        self._records: Deque[dict[str, object]] = deque(maxlen=limit)

    def record(self, snapshot: dict[str, object]) -> None:
        record: dict[str, object] = {"checked_at": snapshot["checked_at"], "state": snapshot["state"]}
        if snapshot["state"] == "OK":
            summary = snapshot["summary"]
            record["peer_count"] = snapshot["peer_count"]
            record["summary"] = {key: summary[key] for key in _SUMMARY_KEYS}
        else:
            record["error_code"] = snapshot["error_code"]
        self._records.append(record)

    def records(self) -> list[dict[str, object]]:
        return deepcopy(list(self._records))
