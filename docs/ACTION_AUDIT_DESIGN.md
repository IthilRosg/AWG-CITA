# Minimal action identity and audit boundary for 0.1.0

This is the action-mode release boundary and its remaining acceptance checks. The
current server has one HTTP Basic Auth account. An account identity can be
audited, but it cannot distinguish people who share that account.

## Identity and policy

The authenticated reverse proxy must overwrite any client-supplied identity
header with its own authenticated account ID before forwarding to the private
relay. The relay must reject missing, duplicate or malformed identity headers,
forward only the validated value, and never trust a header on a public request
without proxy authentication. The application must bind the account ID to its
session at `GET /` and require the same ID on every client read and mutation.

For 0.1.0, one explicitly configured `operator` role may list, create, enable,
disable and delete canary peers. Every route checks this policy server-side.
The role assignment belongs to trusted local configuration, not to a browser
field. The public proxy must authenticate `/` and all API paths, including
static assets if they can reveal operator context. Tests must prove a missing,
forged or changed identity fails before invoking the lifecycle adapter.

If the Basic Auth account is shared by multiple people, audit records identify
the account only. Individual accountability requires separate accounts or a
different authentication provider and is outside this single-account design.

## Durable event sequence

Use a separate service-account-owned, POSIX-local append-only JSONL file for
actions. Reuse the existing descriptor, ownership, no-follow, size and fsync
checks from status evidence, while keeping action events in a distinct file.
The application opens the prepared file at startup and refuses action mode if
it cannot validate the file.

For each authorized POST, append/fsync an `INTENT`
event before calling the adapter. Include schema version, server timestamp,
server-generated correlation ID, validated account ID, operation, opaque target
ID when known, and a hash of the idempotency key. For create, the target is
unknown at intent time. Append/fsync a `RESULT` event with the same correlation
ID, finite result code and resulting opaque ID if known. Never log names,
tags, raw nonces, private/public keys, routes, endpoint, config text, QR data,
cookies, CSRF tokens, request body, raw AWG output or exception strings.
The lifecycle service serializes mutations; the separate action writer serializes
file appends. Correlation IDs pair events even when requests overlap.

If the intent write fails, do not call AWG. If the result write fails after a
possible mutation, return a generic `503`, latch action mode closed and require
operator reconciliation against persistent and runtime state. An unmatched
intent after a crash is an explicit recovery item; the audit must not claim
success or failure without evidence. File rotation is an operator procedure
performed with the service stopped; capacity exhaustion fails closed.

## Acceptance checks

1. Unauthenticated, missing/duplicate/forged identity never reaches the
   adapter; an existing session cannot be reused under a different account.
2. Failed intent fsync causes zero AWG writes. Failed result fsync latches future
   mutations and returns a safe error without replaying one-time secrets.
3. Create, enable, disable, delete, conflict, rollback and lost-response cases
   have paired or explicitly unmatched safe audit events.
4. Audit bytes contain none of the generated configuration or QR payload,
   private/public keys, raw AWG output, credentials or request headers.
5. POSIX tests cover file replacement, symlinks, mode/owner drift, external
   append, partial write, capacity and restart with a trailing complete record.
6. A separate proxy integration test confirms the actual authenticated account
   is injected by the proxy and client-supplied identity is overwritten.

The installed canary candidate implements the single-account check and action
log. Linux CI exercises the failure tests with synthetic data; an isolated copy
of the installed proxy block passed header-replacement checks. A controlled
temporary peer completed create/disable/enable/delete with paired action audit
events and protected-peer readback. Live public authenticated-route identity
verification remains a release acceptance check.
