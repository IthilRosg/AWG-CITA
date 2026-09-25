# AWG CITA

A security-first, self-hosted operator console for **AmneziaWG and WireGuard**.

## Status

Version 0.2.0 provides interface state, safe peer metadata, traffic counters,
a client dossier, bounded status history and a localized operator UI. The
authenticated client registry supports isolated AWG 3.1, AWG 2.0 and plain
WireGuard interfaces with create, enable, disable, delete, and repeat
configuration/QR retrieval. The Profiles menu edits templates for future
client configurations. See [the profile design](docs/MULTI_PROFILE_0_2_0.md).

## Product boundary

AWG CITA is not a generic VPN reseller panel and is not a browser wrapper over
privileged shell access. It is designed around a narrow, allowlisted data model:

- backend bound to loopback;
- reverse-proxy authentication at the public boundary;
- strict Host allowlisting: default loopback names only; a reverse-proxy hostname
  must be passed explicitly through `allowed_hosts` when creating the server;
- read-only status and history omit keys, endpoints, client IDs, raw dumps and
  configuration payloads; authenticated action mode uses opaque client IDs and
  returns a private configuration only to the authenticated operator;
- controlled actions require explicit policy, audit and rollback
  gates.

## Planned milestones

1. Read-only Sector Console UI and safe telemetry.
2. Event history, health signals and append-only audit evidence.
3. Controlled peer lifecycle with explicit approval and rollback.
4. Time-bounded configuration/QR delivery policy.
5. Reproducible releases, threat model and self-hosted deployment guide.

## Inspiration and compatibility

The project takes no code, assets or branding from other panels. Broader projects
such as Amnezia-Web-Panel are useful for feature comparison, while AWG CITA
keeps fixed, separate interfaces and a narrow privileged helper for each.

## Publishing gate

Before the first release: run secret scanning, provide synthetic fixtures and
reproducible tests, and remove all infrastructure-specific deployment data.

## Self-hosting

The package ships an `awg-cita` loopback-only launcher. See the generic
[self-hosted deployment guide](docs/SELF_HOSTED.md) for its least-privilege
boundary, reverse-proxy responsibilities, preflight and rollback checks.

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE).

## V0 read-only HTTP contract

This describes the original read-only mode. The canary lifecycle candidate adds
private, authenticated same-origin routes when explicitly enabled; its release
contract is documented in [CANARY_HTTP_CONTRACT.md](docs/CANARY_HTTP_CONTRACT.md)
and its security boundary in [THREAT_MODEL.md](docs/THREAT_MODEL.md).

- `GET /` serves the operator UI; `GET /api/status` serves the safe telemetry.
- `GET /api/history` serves a bounded, in-process projection of prior safe-status
  results. It retains aggregate metrics or generic error codes only and is cleared
  when the process stops; it never retains peers, keys, endpoints, raw dumps or
  configuration data.
- `HEAD` mirrors these `GET` routes without a body; `OPTIONS /api/status` and
  `OPTIONS /api/history` advertise the read-only methods.
- `POST`, `PUT`, `PATCH` and `DELETE` return `405`; other paths return `404`.
- The server binds only to loopback. A reverse proxy must provide HTTPS and
  authentication, preserve a hostname explicitly listed in `allowed_hosts`, and
  must not expose the loopback listener directly.
