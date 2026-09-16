# AWG CITA

A security-first, self-hosted operator console for **AmneziaWG**.

## Status

Pre-release repository preparation. The first public milestone is a read-only
console: interface state, safe peer metadata, traffic counters, a client
dossier and a localized operator UI. Peer mutations, configuration exports and
QR generation are intentionally out of scope until their threat model, audit
trail and rollback controls are implemented.

## Product boundary

AWG CITA is not a generic VPN reseller panel and is not a browser wrapper over
privileged shell access. It is designed around a narrow, allowlisted data model:

- backend bound to loopback;
- reverse-proxy authentication at the public boundary;
- strict Host allowlisting: default loopback names only; a reverse-proxy hostname
  must be passed explicitly through `allowed_hosts` when creating the server;
- no private keys, peer public keys, endpoints, client IDs, tokens, raw dumps or
  configuration payloads in the UI/API;
- read-only first, with controlled actions added only behind explicit policy,
  confirmation, audit and rollback gates.

## Planned milestones

1. Read-only Sector Console UI and safe telemetry.
2. Event history, health signals and append-only audit evidence.
3. Controlled peer lifecycle with explicit approval and rollback.
4. Time-bounded configuration/QR delivery policy.
5. Reproducible releases, threat model and self-hosted deployment guide.

## Inspiration and compatibility

The project takes no code, assets or branding from other panels. Broader projects
such as Amnezia-Web-Panel are useful for feature comparison, but AWG CITA keeps a
single-protocol, least-privilege operational scope.

## Publishing gate

Before the first release: run secret scanning, provide synthetic fixtures and
reproducible tests, and remove all infrastructure-specific deployment data.

## Self-hosting

The package ships an `awg-cita` loopback-only launcher. See the generic
[self-hosted deployment guide](docs/SELF_HOSTED.md) for its least-privilege
boundary, reverse-proxy responsibilities, preflight and rollback checks.

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE).

## V0 HTTP contract

- `GET /` serves the operator UI; `GET /api/status` serves the safe telemetry.
- `HEAD` mirrors those two `GET` routes without a body; `OPTIONS /api/status`
  advertises those read-only methods.
- `POST`, `PUT`, `PATCH` and `DELETE` return `405`; other paths return `404`.
- The server binds only to loopback. A reverse proxy must provide HTTPS and
  authentication, preserve a hostname explicitly listed in `allowed_hosts`, and
  must not expose the loopback listener directly.
