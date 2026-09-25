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
interface addresses, ports and obfuscation parameters live
in root-owned files and are not editable from the browser. Template updates
use an authenticated, CSRF-protected endpoint and a fixed sudo helper. Only
Delete retains the extra UI confirmation.

The Create result presents Download and Copy first. QR and raw configuration
text stay folded until requested. The existing-client configuration dialog
offers QR, text, and the constrained settings editor. Saved configuration is
private and is never included in status, history, or action audit records.

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
