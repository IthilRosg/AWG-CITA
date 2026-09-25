# Canary action configuration

The action helper requires a host-local JSON file at
`/etc/awg-cita/protected-peer.json`. Keep the directory owned by root and not
writable by group or others. The file must be a regular root-owned file with no
group or other permissions. The helper refuses symlinks and duplicate fields.
Do not commit the populated file or include it in a wheel.

The JSON object has exactly seven fields:

| Field | Meaning |
| --- | --- |
| `public_key` | Base64 public key of the protected, pre-existing peer. |
| `route` | Its exact IPv4 host route in the persistent AWG configuration. |
| `endpoint_host` | Lowercase DNS name used in one-time client configurations. |
| `dns_server` | IP address placed in one-time client configurations. |
| `obfuscation` | Object containing the expected string values for `S1`–`S4` and `H1`–`H4`. |
| `interface_address` | Exact IPv4 interface address and prefix expected in the AWG configuration. |
| `listen_port` | Exact port expected in the AWG configuration and runtime dump. |

The helper checks the protected key and route against the persistent file before
every operation. It checks the obfuscation fields before creating a client.
The client address pool comes from the verified interface address. The listen
port must also match the live runtime dump. A profile change therefore requires
a separate review of both the AWG configuration and this root-owned file.

The application needs `--canary-actions`, `--interface awg-canary0`, one
`--allowed-host`, a matching HTTPS `--operator-origin`, `--operator-id`, and
`--action-audit-log` pointing to a private POSIX-local JSONL file. For example, a
synthetic test host uses `--allowed-host panel.example --operator-origin
https://panel.example:8444`. The relay service must set
`AWG_CITA_OPERATOR_HOST`, `AWG_CITA_OPERATOR_ORIGIN`, and
`AWG_CITA_OPERATOR_ID` to the matching values. The reverse proxy must
authenticate the operator and overwrite any client-supplied `X-AWG-Operator`
header with that account's configured identifier. The relay and application
reject a missing or different identifier. The audit file must be owned by the
service account and mode 0600; startup refuses an unmatched prior intent until
an operator reconciles the peer state.

The private relay socket uses a dedicated `awg-cita-relay` group. Run the
relay as `awg-manager` with that group, create its `/run/awg-cita-relay`
directory as `awg-manager:awg-cita-relay` mode 0750, and grant the Caddy
service only supplementary membership in `awg-cita-relay`. The socket is mode
0660. Do not grant the relay process the Caddy service group: that group can
read the proxy configuration on installations where it owns the Caddyfile.

Install each candidate under a root-owned, service-readable versioned release
directory. The root helper imports from `/opt/awg-cita/current/site`; the
application and relay units must use the same `current` release. Switch the
root-owned `current` symlink only during the reviewed service change, and keep
the previous release intact for rollback. No service account may write the
link, a release directory, or any Python module loaded by the root helper.

If the application unit uses `ProtectSystem=full`, its sudo-invoked root helper
inherits the same read-only mount namespace. Permit only the AWG configuration
directory with `ReadWritePaths=/etc/amnezia/amneziawg`; keep that directory
root-owned mode 0700 and the canary file mode 0600. Verify that the service
user still cannot write the file and that the helper can complete a synthetic
write/restart/rollback test before live actions.

In the Caddy `reverse_proxy` block reached only after `basic_auth`, add:

```caddyfile
header_up X-AWG-Operator {http.auth.user.id}
```

`header_up` replaces all values supplied by the browser. Set `--operator-id`
and `AWG_CITA_OPERATOR_ID` to the single Basic Auth username. Keep Basic Auth
on every route to the relay. Validate the full Caddyfile with `caddy validate`
and prove an unauthenticated request with a forged header receives 401, then
prove an authenticated request with a forged header reaches the relay as the
authenticated username. An isolated copy of the installed operator block has
passed this check; the live authenticated route remains a release acceptance
check.

These settings are a configuration contract, not a deployment procedure. Before
updating a host, inventory the installed helper, service and proxy versions,
back up their configurations, and test rollback with synthetic peers.
