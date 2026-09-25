# Self-hosted deployment guide

This guide covers AWG CITA's **read-only, loopback-only mode**. The optional
canary action mode has a separate private Unix ingress and requires the
[canary configuration contract](CANARY_CONFIG.md) and
[HTTP security contract](CANARY_HTTP_CONTRACT.md). This guide is not a
production-change instruction for any particular host.

## 1. Keep the privilege boundary narrow

The application executes one local AWG inspection command and exposes only its
sanitized result. It does not need peer configuration, keys, endpoint data or
write access to the AWG interface.

Before starting it:

- install AWG CITA from a reviewed wheel or source revision;
- point `--binary` at a root-owned, non-writable-by-service-user AWG executable;
- use a dedicated service account with no interactive login;
- authorize only the exact read-only inspection path required on the target OS;
- do **not** grant unrestricted `sudo`, a shell, broad `CAP_NET_ADMIN`, or write
  access to AWG configuration merely to operate this console;
- keep proxy credentials, TLS private keys and Basic-Auth hashes outside this
  package and outside its logs.

The read-only mode does not require the privileged action helper. Audit and
deploy any host-specific read helper separately.

## 2. Install and start on loopback

Obtain both the exact reviewed wheel and its checksum file through the same
trusted review or release channel. Verify the digest, install that local
artifact into an isolated environment with index access disabled, then invoke
its console entry point. The following names are examples only; replace the
release path, binary path and interface with local audited values.

```sh
sha256sum -c /srv/releases/awg_cita-0.1.0a0-py3-none-any.whl.sha256
python3 -m venv /opt/awg-cita/venv
/opt/awg-cita/venv/bin/pip install --no-index /srv/releases/awg_cita-0.1.0a0-py3-none-any.whl
/opt/awg-cita/venv/bin/awg-cita \
  --binary /usr/local/bin/awg \
  --interface awg0 \
  --bind 127.0.0.1 \
  --port 8788
```

The launcher accepts only `127.0.0.1` or `::1` for `--bind`. It rejects public
or wildcard binds. With no `--allowed-host`, the server accepts only its default
loopback Host names.

When a reverse proxy uses a local backend connection and preserves a hostname,
pass that hostname explicitly, without port or bracket syntax:

```sh
awg-cita --binary /usr/local/bin/awg --interface awg0 \
  --allowed-host panel.example
```

Do not use an IP address with ambiguous formatting; the application requires a
canonical IP literal or a lowercase DNS hostname.

## 3. Add a proxy as a separate boundary

Expose only a reverse proxy, never the AWG CITA listener. The proxy is
responsible for:

- HTTPS certificate lifecycle and modern TLS policy;
- authentication and session policy;
- an explicit upstream connection to loopback;
- preserving only the hostname listed via `--allowed-host`;
- request-size and rate limits appropriate for an operator console;
- access logging that excludes Authorization headers and query secrets.

Test access from the intended operator devices before removing an existing
administrative path. Do not treat this guide as approval to change firewall,
NAT, DNS, certificates or authentication on a live system.

## 4. Service-manager example

Create a service definition only after local preflight. The service should run
as the dedicated account, keep its filesystem read-only, and be started with the
same explicit arguments used in manual verification.

```ini
[Unit]
Description=AWG CITA read-only console
After=network-online.target

[Service]
Type=simple
User=awg-cita
Group=awg-cita
ExecStart=/opt/awg-cita/venv/bin/awg-cita --binary /usr/local/bin/awg --interface awg0 --bind 127.0.0.1 --port 8788 --allowed-host panel.example
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
```

The unit intentionally has no public bind, no credential argument and no peer
mutation capability. Confirm that the local inspection command works under the
service account before enabling automatic start.

## 5. Read-only preflight and rollback

Before any live deployment, record:

1. package version and wheel digest;
2. configured binary path, interface, loopback bind, port and allowed Host names;
3. service account, file ownership and effective permission boundaries;
4. listener state showing loopback only;
5. unauthenticated proxy behavior and authenticated safe-status behavior;
6. the existing service definition and proxy configuration backup location.

Verify with a safe status request that the UI/API contains no keys, endpoints,
addresses, raw dumps or client configuration. Exercise an AWG command failure:
it must return a generic `503` error rather than command output.

Rollback means stopping the new service, removing its proxy route, restoring the
prior known-good service/proxy configuration, and confirming the loopback port
is no longer listening. Peer state must not change during either deployment or
rollback.

## Out of scope

This guide does not authorize peer creation, suspension, deletion, config or QR
export, firewall/routing changes, certificate issuance, authentication changes
or deployment to a specific environment. Each requires an explicit threat model,
change packet, approval and read-back.
