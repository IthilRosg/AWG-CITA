"""Public, read-only and secret-stripping AmneziaWG snapshot helpers."""

from __future__ import annotations


class AwgDumpError(ValueError):
    """The dump cannot be trusted as a safe metrics snapshot."""


ONLINE_AFTER_SECONDS = 5 * 60
STALE_AFTER_SECONDS = 7 * 24 * 60 * 60


def _integer(value: str, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AwgDumpError(f"invalid {field}") from exc
    if number < 0:
        raise AwgDumpError(f"negative {field}")
    return number


def parse_awg_dump(raw: str) -> dict[str, object]:
    """Parse a strict AWG 3.1 dump and discard keys, addresses and endpoints."""
    rows = [line.split("\t") for line in str(raw).splitlines() if line.strip()]
    if not rows or len(rows[0]) != 29:
        raise AwgDumpError("missing interface row")

    listen_port = _integer(rows[0][2], "listen port")
    if not 1 <= listen_port <= 65535:
        raise AwgDumpError("listen port out of range")

    peers: list[dict[str, int]] = []
    for row in rows[1:]:
        if len(row) != 8:
            raise AwgDumpError("malformed peer row")
        peers.append({
            "latest_handshake": _integer(row[4], "latest handshake"),
            "rx_bytes": _integer(row[5], "rx bytes"),
            "tx_bytes": _integer(row[6], "tx bytes"),
        })
    return {"listen_port": listen_port, "peer_count": len(peers), "peers": peers}


def classify_peer(latest_handshake: int | None, now: int) -> str:
    if latest_handshake is None or latest_handshake < 0:
        return "UNKNOWN"
    if latest_handshake == 0:
        return "NEVER"
    age = now - latest_handshake
    if age < 0:
        return "UNKNOWN"
    if age <= ONLINE_AFTER_SECONDS:
        return "ONLINE"
    if age <= STALE_AFTER_SECONDS:
        return "STALE"
    return "OFFLINE"


def build_snapshot(raw: str, *, now: int, interface: str) -> dict[str, object]:
    """Build browser-safe aggregate metrics from a trusted local AWG dump."""
    parsed = parse_awg_dump(raw)
    counts = {state: 0 for state in ("ONLINE", "STALE", "OFFLINE", "NEVER", "UNKNOWN")}
    peers: list[dict[str, int | str]] = []
    rx_bytes = tx_bytes = 0
    for peer in parsed["peers"]:
        status = classify_peer(peer["latest_handshake"], now)
        counts[status] += 1
        rx_bytes += peer["rx_bytes"]
        tx_bytes += peer["tx_bytes"]
        peers.append({**peer, "status": status})
    return {
        "schema_version": 1,
        "interface": interface,
        "listen_port": parsed["listen_port"],
        "peer_count": parsed["peer_count"],
        "summary": {"total": parsed["peer_count"], "online": counts["ONLINE"], "stale": counts["STALE"], "offline": counts["OFFLINE"], "never": counts["NEVER"], "unknown": counts["UNKNOWN"], "rx_bytes": rx_bytes, "tx_bytes": tx_bytes},
        "peers": peers,
    }
