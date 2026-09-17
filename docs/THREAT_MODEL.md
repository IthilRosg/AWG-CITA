# AWG CITA threat model (draft)

## Assets that must not leave the host

- server and client private keys;
- peer public keys, endpoints, allowed IPs and raw `awg show … dump` output;
- generated client configurations, QR payloads, tokens and client identifiers;
- proxy credentials and administrative session material.

## Trust boundaries

1. The privileged AWG read helper is host-local and allowlisted.
2. The application reads only a sanitized snapshot and binds to loopback.
3. A reverse proxy provides HTTPS and authentication outside the app process.
4. The browser receives only safe operational metadata.

## V0 guarantees

- `GET /api/status` serves the current safe telemetry; `GET /api/history`
  serves a bounded in-process history of aggregate-safe results only; `GET /`
  serves the UI.
- History is cleared on process restart and excludes peers, keys, endpoints, raw
  dumps, addresses, configurations and arbitrary command output.
- `HEAD` mirrors each GET route and `OPTIONS` documents the read-only method
  set. Mutation methods are refused.
- Host headers are parsed strictly and must match loopback defaults or an
  explicit reverse-proxy `allowed_hosts` entry.
- The strict parser accepts the documented AWG layout only and discards sensitive
  fields before constructing a snapshot.
- The UI identifies peers only by stable ordinal label; it does not expose keys,
  endpoints or address data.
- A read failure returns a generic error code, not command output.

## Designed V0.3 audit evidence boundary

Persistent evidence is not enabled in V0.2. The proposed narrow V0.3 scope is
documented in [AUDIT_EVIDENCE_DESIGN.md](AUDIT_EVIDENCE_DESIGN.md): an
operator-opt-in, POSIX-local append-only JSONL file containing a newly
constructed, aggregate-only projection of sampled accepted `GET /api/status`
results. This is a local disk side effect, while the service remains read-only
with respect to AWG and peer configuration. It is not an API route, database,
remote log sink, peer audit trail, or tamper-proof ledger.

The design requires explicit absolute-path configuration, a retained
descriptor opened through no-follow POSIX traversal, restrictive
service-account permissions, interval sampling, a fixed byte limit, serialized
append/flush, and generic fail-closed behavior on a write error. It must not
retain raw dumps, exception details, stderr, request metadata, peer lists, keys,
endpoints, addresses, configurations, credentials, tokens or client
identifiers.

## Explicit non-goals

V0 does not create, suspend, rotate, revoke or delete peers. It does not issue a
configuration or QR code. Those controls require a separate threat-model update,
confirmation workflow, append-only audit record, bounded export policy, backup
and tested rollback.

## Release requirements

A public release must ship synthetic fixtures only, run secret scanning in CI,
include reproducible tests, document reverse-proxy configuration without real
hostnames, and never include environment-specific deployment scripts or backups.
