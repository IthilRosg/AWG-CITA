# Reproducible panel deployment

Application revision is pinned to d8d5257461cc31d9ef715396fba01fc7d11660dd.
The deployment revision is independent. Supported host: Ubuntu 24.04 amd64,
systemd, Python 3.12, sudo, and an existing compatible AWG userspace binary.
No kernel modules, VPN interfaces, profiles, clients, routes, firewall, DNS,
SSH settings or operator credentials are provisioned by this installer.

Build a host-specific bundle with `python3 deploy/build.py --config HOST.json
--wheel APPROVED.whl --dependencies WHEELHOUSE --out OUTPUT`. Only an approved
application wheel with the locked SHA is accepted. CI reconstructs that wheel
from the pinned Git commit, including its original CRLF source bytes.
The wheelhouse must contain exactly the two locked Linux dependencies.
`manifest.json` is generated from the supplied bytes, including extracted
Python packages, native bcrypt extension, wrappers, units and host parameters.

Host configuration is not a credential file. Use the example as a schema,
verify each field against the destination host, and never copy a production
credential into Git. The immutable application supports the listed interface
and profile paths only; other mappings fail closed before installation.
This limitation is explicit rather than silently substituting host values.

Run `sudo python3 install.py preflight BUNDLE`, then `install BUNDLE`.
Preflight does not write to the host. Installation snapshots original files,
unit existence/enabled/active state and current target before any host write.
The transaction path is printed. `rollback TRANSACTION` restores that state;
if no old units existed, it removes the new units rather than starting an
imaginary old deployment. Releases and newly appended audit data are retained.
Created service accounts and non-empty state directories are retained on
rollback to preserve audit ownership; their creation is recorded explicitly.

Existing Caddy config and credentials must already be correct. This installer
does not reload/restart Caddy. Its running process must already have access to
the relay group; otherwise installation is blocked. Configuring Caddy and
credential provisioning on a brand-new host are explicit prerequisites.

AWG is not copied into this bundle. `external-lock.json` records the upstream,
tag, license and official Linux artifact. A host may retain its installed
compatible binary with its own approved SHA, without attributing that binary
to the official artifact. No automatic `latest` download occurs at install.

The clean-host systemd test uses synthetic profiles and a clearly labelled
AWG fixture. It separately executes the locked genuine AWG `--version` and
read-only `show interfaces`; the fixture test does not prove kernel/tunnel
compatibility. Production acceptance also requires genuine AWG read-back and
unchanged host-specific VPN hashes/counts/peer sets.
