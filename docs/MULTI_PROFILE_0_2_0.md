# Connection profiles in 0.2.0

The operator panel has three isolated client registries: AWG 3.1, AWG 2.0 and
plain WireGuard. A peer belongs to exactly one server interface. Its private
key and saved configuration are never converted into another protocol. Each
profile provides Create, Enable, Disable, Delete, configuration download and
QR. The existing AWG 3.1 API paths remain valid.

The Profiles menu edits DNS, AllowedIPs, MTU and keepalive for **future**
client files. Each existing client's configuration can also edit these four
fields separately. A saved edit replaces that client's protected `.conf` and
regenerates its QR; it never changes keys, address, endpoint, server peer or
obfuscation parameters. The editor checks a revision token before an atomic
write, so a stale browser tab cannot silently overwrite a newer file. Server
interface addresses and obfuscation parameters live
in root-owned files and are not editable from the browser. Template updates
use an authenticated, CSRF-protected endpoint and a fixed sudo helper. Only
Delete retains the extra UI confirmation.

The Create result presents Download and Copy first. QR and raw configuration
text stay folded until requested. The existing-client configuration dialog
offers QR, text, and the constrained settings editor. Saved configuration is
private and is never included in status, history, or action audit records.

The Settings view also shows an authenticated, read-only server summary for
each profile: interface, endpoint, interface address, listen port, active state,
and managed client count. The fixed root helpers verify profile and runtime
port before returning this projection. They never return private/public keys,
raw AWG dumps, or obfuscation values. Address and obfuscation changes need a
separate client migration workflow.

The endpoint host now has an authenticated editor in Settings. It changes only
the root-owned profile metadata with an optimistic revision check, private
backup, atomic replacement, readback, and rollback on verification failure.
VPN interfaces are not restarted. Existing saved client configurations are
projected with the current endpoint on each download, QR, and edit; keys and
client-specific fields are preserved. Files already imported into a client
must be downloaded and imported again after an endpoint change. Address and
obfuscation remain read-only because they require a coordinated client and
runtime migration. An endpoint update does not prove external reachability.

The listen port has a separate maintenance action. Its preflight rejects an
occupied port, a pre-existing UFW rule for that port, or a missing rule for the
current port. It opens the new UDP port before changing the persistent
interface config and root-owned metadata, restarts only the selected interface,
and verifies runtime port and peer inventory. On failure it restores both
files and the old runtime, then removes the newly opened rule. A private
operation journal restores the old state on the next helper call after an
interrupted migration; private backups remain for manual recovery. On success
the old UFW rule remains during the
client migration window; remove it only after checking that clients have
imported newly downloaded configurations. Clients using previously imported
files disconnect when the interface switches ports. The dashboard and SSH
service are not restarted by this action.

## Isolation and installation

`awg-cita2` and `awg-cita-wg` are independent interfaces and systemd services.
Their address, port, endpoint and egress device are installation parameters,
not repository constants. The root-owned installer refuses occupied ports,
overlapping routes and existing target files. The AWG 2.0 interface uses all
S1–S4 and H1–H4 parameters without HeaderProtectionKey. The plain WG
interface has no AWG obfuscation parameters. Both use the pinned AWG userspace
stack, which supports the compatible WireGuard mode.

The fixed profile helper accepts only `awg2` and `wg` plus a small operation
allowlist. Per-profile locks, backups and root-only stored configurations are
separate. The operator backend retains its private Unix socket, session and
CSRF checks. The systemd drop-in allows writes only to the root-owned template
directory. Sudoers grants only the fixed helper commands.

The install script requires explicit `--endpoint-host`, `--egress-interface`,
`--dns-server`, `--awg2-address`, `--awg2-port`, `--wg-address` and `--wg-port`.
Populate client templates and install both fixed helpers and sudoers before
switching the versioned application release. Validate services and the three
profile API paths after the switch; retain the previous release symlink for
rollback.

Server startup, peer Create/config/Delete and API readback were verified for
both additional profiles. A handshake from an external AWG 2.0 or WG client
must be checked separately on the target device before treating end-to-end
connectivity as verified.
