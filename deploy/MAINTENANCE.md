# Deployment maintenance

The accepted application contract is commit
`d8d5257461cc31d9ef715396fba01fc7d11660dd`. Deployment revision `fe86824`
was tested separately and installed without changing that application source.
The tag `panel-deployment-fe86824`, its target and published asset bytes are
immutable. Maintenance PRs do not authorize production deployment.

## Dependency update process

1. Discover new versions or security advisories from official package indexes,
   the upstream AWG repository and supported OS release notes. Discovery does
   not update a host or select an unpinned `latest` during installation.
2. Open a PR with selected versions, official sources, license/architecture
   compatibility and exact artifact SHA256. Update runtime requirements,
   build requirements and `external-lock.json` consistently. Explain each
   change and any change to supported Python/Ubuntu versions.
3. Rebuild the approved wheel and bundles from clean source. Verify actual
   bytes, installed file hashes and imports. Retain prior manifests/artifacts;
   generate a new deployment manifest version.
4. Run application/root POSIX/browser contracts and clean Ubuntu/systemd CI
   for standard and legacy units: service-user rights, real bcrypt login,
   helper/sudoers boundaries, sockets, fail-before-switch, repeat install and
   rollback. Separate genuine AWG checks from fixture-only results.
5. Review the PR, create a new immutable release/tag and checksums, then obtain
   approval for the concrete host deployment. Take its own baseline and
   rollback transaction; run preflight, install and live acceptance. Never
   replace an existing tag or artifact in place.

## Moving beyond the pinned application

Changing the application commit is a contract change, not only a wheel swap.
One reviewed PR must consistently update the application commit, approved
wheel hash/size, source date epoch/build reproduction, runtime file selections,
build assertions, clean-host CI assertions, release marker/naming and
compatibility documentation. Recheck fixed profile/interface adapters and
privileged helper interfaces. Unknown wheel bytes must still fail closed.

Run privacy/journal/auth contracts and deployment acceptance against the same
concrete revision. Retain the old bundle and independent host rollback.

## Host operations

- Follow `README.md` and `PROVENANCE.md`. Verify host parameters and existing
  credentials/Caddy/VPN prerequisites; do not copy another host's secrets,
  origin, profiles, client files or audit data.
- Retain the exact installer/manifest with its SHA256. Use that bundle for
  preflight, verify and rollback rather than the newest maintenance checkout.
- Record the actual unit pair. Absence of standard names does not prove an
  absent installation: legacy backend/relay names are supported too.
- Check both sockets, Caddy group access, external login, client lists and
  authenticated actions API. Compare the host's own VPN hashes and sorted peer
  sets; another host's client count is not a baseline.
- Keep the transaction path. Rollback restores original files/current and
  enabled/active unit states; appended journals and releases are retained.
  Do not truncate audit history or copy runtime sockets from another host.
- Separate process network restrictions, routing, SSH identity and SSH
  authentication. A local permission error does not establish VPN filtering.

This process introduces no automatic production update, credential change,
network mutation or production canary mutation.
