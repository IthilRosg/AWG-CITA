# AWG CITA threat model (0.1.0 candidate)

This model covers the read-only console and the optional canary peer actions in
the current development tree. Action mode is deployed as a canary candidate but
is not yet approved for a published release. The original read-only mode remains
available when actions are off.

## Protected assets and permitted browser data

The server private key, generated client private keys, peer public keys, raw AWG
dumps, peer routes, endpoints, persistent AWG configuration, root-owned profile,
proxy credentials, session cookies and CSRF tokens remain within their intended
trust boundaries. The browser receives bounded operational metadata and opaque
client IDs for the authenticated operator. A successful create response is the
single exception: it includes a client configuration and QR payload for one-time
delivery. Neither is included in status/history or mutation audit records.

The client ID is derived from a public-key hash. It is pseudonymous metadata,
not an authorization token and not a substitute for checking the protected
peer against the root-owned profile.

## Trust boundaries

1. The public reverse proxy supplies HTTPS, authenticates operators and
   overwrites the operator identity header. The application requires the one
   configured account ID and binds it to the action session created by `GET /`.
   A proxy route that bypasses authentication remains a critical failure.
2. The rate-limit relay accepts requests from the proxy over a private Unix
   socket, forwards only the configured Host and selected headers, and connects
   to the application over another private Unix socket. Action mode refuses a
   TCP listener outside explicit test mode. Read-only mode binds to loopback.
3. The application validates Host, session cookie, exact Origin, CSRF token,
   content type and bounded request length before calling the lifecycle domain.
   A session lasts at most one hour and is lost on restart. Responses use
   `Cache-Control: no-store`, a restrictive CSP and no-referrer policy.
4. The service account can call only the fixed root helper through sudo. The
   helper validates its fixed verbs and peer-ID shape, takes a bounded lock,
   reads the root-owned profile and AWG config, protects the designated original
   peer, and confines writes to the canary configuration. The profile file is
   root-owned, private and outside the package.

## Mutation and secret-delivery behavior

- Create validates input and profile, generates keys and the QR payload before
  writing, backs up the prior config, replaces it, restarts the canary interface
  and checks readback. It returns configuration material only on success.
- Enable, disable and delete use the same backup, replace, restart and readback
  path. On a detected failure, the controller attempts to restore the prior
  configuration and runtime. A process or host crash between those steps is not
  covered by automatic recovery; deployment preflight and rollback must check
  both persistent and runtime state.
- A create nonce is recorded in the persistent configuration. Reusing it never
  reissues the private key or QR payload. A lost create response must be
  reconciled through a safe client-list read and operator cleanup, not an
  automatic retry.
- Enable, disable and delete idempotency results are bounded in memory. They
  are cleared on restart, so the client must read canonical state after an
  ambiguous response.
- The helper and adapter suppress raw command output and exceptions in HTTP
  errors. Backups and the protected profile are local privileged data and must
  not be copied into release artifacts or ordinary logs.

## Audit and remaining release blockers

The status evidence file records aggregate read-only status samples. The
lifecycle domain also keeps bounded diagnostic events in memory. Action mode
has a separate, durable JSONL intent/result log tied to one configured operator
account. It fails closed on write failure or an unmatched intent at startup.
The account ID cannot distinguish people who share credentials.

The installed proxy block was tested in isolation for identity replacement.
The live public route rejects unauthenticated requests carrying a forged
operator header, and the installed Caddyfile validates with the same header
replacement rule. An authenticated browser loaded the installed panel. These
checks form the reviewed proxy-identity evidence; an authenticated forged-header
request through the live public route was not performed. A temporary peer
completed create/disable/enable/delete with matched, secret-safe audit pairs
and protected-peer readback. The final package was installed from a verified
wheel, and an isolated rollback switch was rehearsed; an earlier cutover also
exercised a live rollback. Linux CI exercises the privileged helper and failure
paths against synthetic files.

## Release requirements

Public artifacts contain synthetic fixtures only. CI runs the public safety
scan, full Python and browser suites, isolated privileged-helper tests, and a
clean wheel install. Deployment-specific profiles, credentials, service files
and backups remain outside the public package.
