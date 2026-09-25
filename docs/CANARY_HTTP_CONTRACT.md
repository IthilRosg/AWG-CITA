# Canary HTTP contract (0.1.2)

This contract describes the current action-mode implementation. It is enabled
only with `--canary-actions`, a private Unix application socket and a matching
HTTPS operator origin. The historical Sprint 4 mock contract is retained as a
record of the earlier design phase.

## Routes

| Method and path | Request | Success |
| --- | --- | --- |
| `GET /` | None | UI with a one-hour application session cookie and CSRF token. |
| `GET /api/clients` | Session cookie | `{schema_version: 1, clients: [...]}` with at most 64 safe records. |
| `GET /api/clients/{peer-id}/config` | Session cookie | `200` with the retained `configText` and `qrDataUri`. |
| `POST /api/clients` | `name`, `tags`, `idempotencyKey`, `acknowledged: true` | `200` with a safe client record, `configText`, `qrDataUri`, `oneTime: false`. |
| `POST /api/clients/{peer-id}/enable` | `idempotencyKey` | `200` with canonical client record. |
| `POST /api/clients/{peer-id}/disable` | `idempotencyKey`, `reason: "operator_requested"` | `200` with canonical client record. |
| `POST /api/clients/{peer-id}/delete` | `idempotencyKey`, `confirmation: true` | `200` with `{schema_version: 1, id, deleted: true}`. |

Peer IDs in action paths have the form `peer-` followed by sixteen lowercase
hexadecimal characters. The server does not expose raw public keys. Update and
mock configuration-preview routes are not part of the real action API. Read-only
`/api/status` and `/api/history` retain their existing contracts.

The authenticated proxy supplies exactly one `X-AWG-Operator` header. The
application binds its configured identifier to the session and verifies it on
client reads and mutations. Every POST requires exactly one valid session cookie, exact configured Origin,
matching `X-CSRF-Token`, `Content-Type: application/json`, and a decimal
`Content-Length` from 1 through 2048. Transfer-Encoding is refused. The app
accepts only the listed JSON fields and validates values again on the server.
The reverse proxy must authenticate before forwarding any route that issues a
session or reaches the action API. It must not expose the private backend socket.

Responses use `Cache-Control: no-store`. The session cookie is HttpOnly and
SameSite=Strict, with Secure set for HTTPS operator origins. Configurations
are stored in a root-only directory for repeat retrieval. They are not cached
in the browser or lifecycle service and are removed when a client is deleted.
If the create response is lost after commit, the caller can retrieve the
configuration from the client menu. Old peers require migration of a saved
configuration before repeat retrieval becomes possible.

## Errors and limits

The application returns finite error codes: `400` for invalid requests, `401`
for missing/expired session, `403` for Origin or CSRF failure, `404` for unknown
routes or clients, `409` for conflicts, `415` for unsupported content type,
`421` for untrusted Host, and `503` for internal or AWG failures. Unsupported
mutation methods return `405`. The relay can return `429` when its rate or
concurrency limits are reached. Raw AWG output, private keys and exception
details are never error payloads.

The relay currently allows three concurrent action/list requests and applies
process-local token buckets. The application bounds sessions to 128. These
limits are operational controls, not operator authorization.

## Remaining release checks

The application writes a separate durable intent/result action log and fails
closed if it cannot append. A missing result after a possible mutation requires
operator reconciliation before restart. The installed proxy block passed an
isolated Basic Auth header-replacement test. A temporary canary peer completed
the full lifecycle with protected-peer readback and action audit. The live
authenticated-route identity check remains a release gate.
