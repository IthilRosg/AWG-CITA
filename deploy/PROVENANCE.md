# Deployment source provenance

Application source is unchanged at d8d5257461cc31d9ef715396fba01fc7d11660dd.
Deployment is a separately versioned revision.

| Component | Origin | Deployment treatment |
|---|---|---|
| peer wrapper | `scripts/awg-cita-peer`, introduced by c07dfe6b1c2cabf7587c1302b5fe916bf91b2723 | Exact Git blob; SHA aedddc2a6a6422b58036ca3df6eaebc23a2ded4254fdc530447af188aabd7787 matches inventoried host |
| profile wrapper | `scripts/awg-cita-profile`, 8331f759951c14c6e7106f1530c8a0a4255b0da1 | Exact Git blob; SHA f1eed18bc2c8e2e9cd761b77afcc373ef424b46fb2be31e5f708f57ce81a5d10 matches inventoried host |
| template wrapper | `scripts/awg-cita-template`, same introduction | Exact Git blob; SHA 0cc6346919008c679247d509bf422e0b5f813f1d85141a381c4b70d74353d45c matches inventoried host |
| read wrapper | host inventory, shell source reviewed 2026-11-08 | Exact argument allowlist retained; template rendered without host credentials |
| manager read | SE1 fixed read command plus DE-2's live Python redaction boundary, reviewed 2026-11-08 | No arguments accepted; AWG path explicitly configured and SHA checked; 29/8-column schema enforced; private/PSK/header-protection fields redacted before leaving root |
| sudoers | immutable `scripts/*sudoers` plus inventoried read helper policy | No arbitrary-command grant; read command tightened to empty argument string; helper itself also rejects arguments |
| systemd templates | live inventoried backend/relay units and drop-ins | Host/origin/auth path rendered from validated input; relay gains deterministic PYTHONPATH for bundled bcrypt |
| Caddy supplementary group | inventoried service drop-in | Existing running group access is a prerequisite; installer never reloads Caddy |
| segno / bcrypt | official PyPI wheels | Versions, exact wheel filenames and SHA locked; both unpacked offline into versioned site, no reliance on host site-packages |
| AWG | official amnezia-vpn upstream | Source/tag/commit/license, zip SHA and binary SHA in external-lock; existing host binary may be independently approved and reused without replacement |

The inventoried host binary identifies as v3.1.20260812, but its SHA differs
from the upstream prebuilt artifact. We do not attribute its build to upstream,
ship it, or infer a version from its containing directory. Host reuse requires
its own explicit SHA and read-only compatibility checks. Distribution uses only
the upstream artifact with verified SHA and GPL-2.0 provenance.

## Runtime manifest v2

The prior application-only manifest is retained unchanged. `build.py` generates
a new manifest per concrete host bundle, divided into:

- application runtime (approved wheel, extracted package/static, relay/auth);
- privileged helper runtime (fixed wrappers and sudoers);
- systemd deployment (two units and Caddy group drop-in);
- external artifacts/dependencies (offline wheels with locked hashes);
- host-specific prerequisites (validated non-secret host parameters);
- excluded secrets/configuration (never copied from a source server).

Every installed regular file has source, destination, bytes, SHA256, owner,
group, mode and section. `SHA256SUMS` covers the manifest and installer; the
outer release archive must also be checked against its approved SHA before
execution. Directories, accounts and generated sockets are installer-managed
state, not copied artifacts. The transaction records newly created accounts
and state directories. Retaining these on rollback preserves appended audit
events and their owner identity. No client settings or logs go into Git.
