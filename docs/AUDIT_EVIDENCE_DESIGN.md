# Persistent audit evidence design

## Status

Implemented V0.3 candidate. Persistence remains disabled by default; the
feature is enabled only by an explicit local CLI option. This document does not
authorize a deployed-host change or add an HTTP endpoint.

## Goal and boundary

An operator may opt in to local, machine-readable evidence of aggregate status
outcomes across process restarts. This is health and incident-correlation data,
not peer administration, configuration recovery, billing, activity monitoring,
or a tamper-proof ledger.

The current service is read-only with respect to AWG and peer configuration. In
opt-in audit mode, an accepted `GET /api/status` can have the deliberate local
side effect of appending safe evidence. It remains read-only with respect to
AWG, peers, proxy configuration, and browser-visible data. `HEAD /api/status`
does not write evidence even though it performs a telemetry read.

## Non-goals

This scope must not add peer CRUD, peer identifiers or detail, keys, endpoints,
addresses, raw AWG output, configurations, QR payloads, credentials, tokens,
remote shipping, analytics, a database, an audit API route, automatic rotation,
or production deployment automation.

Aggregate timestamps, peer counts, traffic totals, and availability outcomes
are sensitive operational metadata. Only the service account and explicitly
authorized local operators may read or replace the evidence file. A host
administrator can modify it; JSONL does not provide tamper evidence.

## Normative event schema

The writer creates a fresh dictionary. It never serializes arbitrary source
fields. It generates `checked_at` itself at event acceptance as canonical UTC
RFC 3339 text (`YYYY-MM-DDTHH:MM:SS+00:00`), rather than trusting a source
string. Compact UTF-8 JSON plus one trailing newline must be at most 512 bytes.

Every event has exactly `schema_version`, `kind`, `checked_at`, and `state`:

- `schema_version` is integer `1`;
- `kind` is the literal string `status`;
- `state` is exactly `OK` or `ERROR`.

An `OK` event has exactly `peer_count` and `summary` in addition to those keys.
`peer_count` is a non-boolean integer from `0` through `2_147_483_647`.
`summary` has exactly `total`, `online`, `stale`, `offline`, `never`, `unknown`,
`rx_bytes`, and `tx_bytes`. Counts are non-boolean integers from `0` through
`2_147_483_647`; byte totals are non-boolean integers from `0` through
`18_446_744_073_709_551_615`. `peer_count == total`, and
`total == online + stale + offline + never + unknown`.

An `ERROR` event has exactly `error_code` in addition to the common keys.
`error_code` is one of `awg_output_too_large`, `invalid_awg_dump`, or
`awg_command_failed`. It is never an exception message. These exact rules are
the emitted-event validation boundary; missing, incorrectly typed, out-of-range,
or inconsistent allowlisted values are an audit failure. Extra source fields
are deliberately ignored and never serialized.

The resulting record shapes are:

```json
{"schema_version":1,"kind":"status","checked_at":"2026-01-01T00:00:00+00:00","state":"OK","peer_count":4,"summary":{"total":4,"online":1,"stale":0,"offline":2,"never":1,"unknown":0,"rx_bytes":12,"tx_bytes":34}}
```

```json
{"schema_version":1,"kind":"status","checked_at":"2026-01-01T00:00:00+00:00","state":"ERROR","error_code":"awg_command_failed"}
```

The writer must never retain exception text, stderr, raw command output,
request headers or paths, client addresses, environment, command arguments, or
injected extra mappings.

## Enablement and availability

Persistence is disabled by default. The CLI accepts `--audit-log PATH` and the
optional `--audit-min-interval SECONDS`; the interval is a non-boolean integer
from 60 through 3600 and is rejected unless audit mode is selected. Audit mode
is valid only on POSIX hosts. Requesting audit mode on any other platform is a
startup error, not a weaker cross-platform fallback.
`PATH` is absolute. The parent directory must already exist; the service never
creates directories, changes ownership or permissions, or follows an
operator-supplied symlink.

The fixed default minimum interval is 60 seconds. At most one evidence event is
accepted in each interval, regardless of request volume; the first accepted
`GET /api/status` after an interval boundary supplies that event. A rejected
Host, static asset request, `/api/history`, `HEAD`, `OPTIONS`, or unsupported
method produces none. A future generic deployment guide must require upstream
authentication and a rate limit for the status route before audit mode is used.

A caller who can issue accepted status reads can still eventually consume the
fixed capacity. This is an explicit availability boundary, not a security
claim. When capacity is exhausted, a writer state flag latches under its lock;
all later accepted `GET /api/status` requests return a generic audit failure
until a controlled service restart with a newly prepared evidence file.

## Secure POSIX file lifecycle

The first implementation supports POSIX only. It opens and retains one verified
file descriptor for the whole process lifetime; it does not reopen by pathname
per event.

Before accepting requests, the implementation must traverse the absolute parent
path descriptor-by-descriptor using `openat`-style operations with
`O_DIRECTORY|O_NOFOLLOW`, rejecting a missing component, symlink, or non-
directory ancestor. It opens the leaf relative to that verified parent
descriptor with `O_WRONLY|O_APPEND|O_NOFOLLOW|O_CLOEXEC` and `O_CREAT` only for
a new regular filename; the creation mode is `0600`. It then validates the
opened descriptor with `fstat`:

- it is a regular file owned by the effective service UID;
- `st_nlink == 1`;
- no group or other permission bit is present (`st_mode & 0o077 == 0`);
- it remains in the expected verified parent directory; and
- its current size is at most the configured 1 MiB cap.

A pre-existing file is accepted only when all validation rules already hold.
The process never repairs permissions or ownership. It retains the descriptor,
so a path replacement after startup cannot redirect future writes. A detected
short write, write/flush error, descriptor identity failure, or external
truncation/growth inconsistent with the retained descriptor latches the same
failure state. Files with any non-newline trailing bytes are rejected at
startup; the implementation does not truncate or repair a partial record.

This is operational evidence, not durable or crash-proof storage. The initial
version flushes after each complete append but does not claim `fsync` durability
or complete-record recovery after a power loss. The documented controlled
recovery is to stop the service, preserve the failed file as evidence, create a
new operator-owned `0600` empty file in the trusted directory, and restart.

## Request and error ordering

For every eligible accepted `GET /api/status`, the application first checks the
writer's latched state under its lock. A latched failure always takes precedence
over interval sampling and returns the audit-failure response below; it never
updates browser history or returns a normal status response. Otherwise, the
application obtains the normal sanitized snapshot, validates and writes its
safe projection if the interval is due, then records the same snapshot in
in-memory browser history, then sends the normal existing response. If no
evidence event is due, it records history and responds normally.

If projection, size validation, write, flush, or descriptor validation fails,
the writer latches failure; the snapshot is not added to history and the server
responds with HTTP `503` and exactly:

```json
{"schema_version":1,"state":"ERROR","error_code":"audit_write_failed","checked_at":"<server-generated UTC timestamp>"}
```

No underlying error text appears in the HTTP response, history, evidence, or
standard request log. A failure before a complete append creates no evidence
event. If a complete append succeeds but `fsync` reports failure, the safe event
may already exist; the response still fails closed, browser history remains
unchanged, and the writer latches until controlled recovery.

## Capacity and concurrency

The cap is exactly 1 MiB (`1_048_576` encoded bytes), including trailing
newlines. Under one process-local lock, the writer validates retained-descriptor
and parent-leaf identity, validates/encodes one complete record, confirms that
`current_size + encoded_record_length <= cap`, appends, verifies the full byte
count, flushes, then revalidates exact final size and identity before reporting
success. It never truncates, rewrites, compresses, rotates, or deletes evidence
automatically. Requests waiting on the lock observe the latched failure state
before writing.

An operator archives and replaces a file only during controlled maintenance
with the service stopped. The candidate issues `fsync` after each append but
does not claim crash-proof durability; stronger durability guarantees require a
separate design. Rotation, remote storage, multi-process writers, Windows
support, or cryptographic tamper evidence each also require separate review.

## Tests required before implementation is accepted

1. Audit mode is absent unless explicitly configured and fails startup on
   non-POSIX hosts.
2. Both exact schemas validate; malicious strings, unknown codes, booleans,
   negative/oversized values, extra keys, and inconsistent totals fail closed.
3. Only writer-generated canonical timestamps are stored; prohibited fields and
   injected source data never appear.
4. Relative paths, missing parents, all symlinked ancestors/leaf targets,
   special files, hard links, unsafe modes/owner, and invalid existing trailing
   bytes fail startup.
5. Descriptor-relative open, post-open `fstat`, retained-descriptor use, and
   path replacement resistance are covered on POSIX.
6. Short write, flush failure, external size change, cap exhaustion, and waiting
   concurrent requests latch failure and return only `audit_write_failed`,
   including a request for which no evidence event would otherwise be due.
7. A capped append cannot partially modify prior records; concurrent successful
   writes are independently parseable JSON Lines with no interleaving.
8. Interval sampling, `GET` eligibility, and no-write behavior for `HEAD`,
   history, rejected Host, assets, `OPTIONS`, and mutations are covered.
9. `/api/history` remains in-memory-only; existing loopback, strict Host, CSP,
   read-only method, browser, wheel, and public-safety gates remain green.

## Production gate

Before use on a production host, create a separate change record with exact
service UID, target directory, ownership/mode read-back, upstream auth/rate
limit, backup/rollback procedure, synthetic canary, and verification from the
user's computer and phone. This design does not authorize deployment or changes
to AWG peers, UDP transport, firewall/NAT, proxy authentication, or existing
administrative paths.
