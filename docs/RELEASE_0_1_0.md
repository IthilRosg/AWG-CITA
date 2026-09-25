# 0.1.0 release gate

The release includes canary peer creation, enable, disable, delete, and one-time
configuration delivery. None of these operations should be promoted from the
development candidate until every gate below passes against the same commit and
wheel.

## Blocking gates

1. Review the new portable configuration boundary and privileged installation
   details. The public safety scan must pass on the complete candidate.
2. Review the [threat model](THREAT_MODEL.md) and
   [HTTP contract](CANARY_HTTP_CONTRACT.md). Verify the local identity and action
   audit implementation against the [action-audit design](ACTION_AUDIT_DESIGN.md),
   including proxy header replacement and recovery tests.
3. Run the full Python suite on supported Linux and Windows versions. Linux must
   exercise the privileged helper against isolated synthetic files and commands.
4. Run every browser scenario, including real-adapter boundary, create,
   lost-response recovery, enable, disable, and delete.
5. Build a wheel with its declared dependencies, install it in a clean
   environment, and verify package assets and the command-line entry point.
6. Identify the exact installed server revision before deployment. Record the
   candidate wheel digest, preflight, backup, health checks, and rollback steps.
   Production mutation requires a separately reviewed acceptance run.

## Current evidence

- Local Python suite passes on Windows; POSIX-only tests must pass in Linux CI.
- Local browser scenarios: mock UI, adapter boundary, real canary mutation, and
  one-time create/lost-response scenarios pass against synthetic fixtures.
- Isolated wheel build/install smoke test passes.
- Public safety scan passes on the current development candidate. The canary
  configuration contract is described in [CANARY_CONFIG.md](CANARY_CONFIG.md).
- A versioned `0.1.0` wheel candidate is installed on the operator host. The
  application and relay use private Unix sockets; the protected original peer
  profile and action audit are installed with restricted permissions. The
  precise host, artifact digest, baseline and rollback evidence remain in the
  private migration packet under `.ops-tmp/`.
- A read-only Playwright smoke check loaded the installed `0.1.0` panel assets through
  the private relay and confirmed real-canary mode and one live peer. Public
  unauthenticated requests, including requests with a forged operator header,
  returned `401` on the tested page, API and static routes.
- An isolated copy of the installed Caddy operator block rejected an
  unauthenticated request and replaced a forged identity header with the
  authenticated test account before forwarding. This does not replace an
  authenticated end-to-end check of the live public route.
- A controlled temporary peer was created, disabled, enabled and deleted on
  the installed canary candidate. One-time configuration and QR were checked
  in memory, then discarded. Persistent and runtime state returned to the one
  protected original peer. The only persistent addition is the intended
  idempotency nonce marker; a trailing blank line remains after deletion.
  Action audit contains matched intent/result pairs for the successful cycle
  and for two earlier failed create attempts. No secret markers appeared in
  audit bytes.
- The installed host retained the prior versioned release. An isolated
  symlink rehearsal switched from the current release to the prior release
  and back, importing the package at both targets. The production symlink and
  services stayed unchanged and healthy. This verifies the switching mechanism,
  not a live service rollback or a restored peer state after a crash.
- Reachable Git history and the intended public file set were scanned for
  embedded credentials, private-key files, host-specific markers and large or
  binary artifacts. Flagged assignments were synthetic test fixtures. The
  server's protected configuration and backup remain private.
- The final `0.1.0` wheel was installed from a versioned release, with its
  digest, metadata and assets checked on the operator host. Runtime package
  files match the accepted canary build. CI passed for the final candidate on
  Python 3.11–3.13 and the browser suite.

The proxy identity gate uses the reviewed equivalent in the
[threat model](THREAT_MODEL.md): the installed Caddy block passed an isolated
authenticated-header replacement test, the live config validates with that
rule, the live route rejects forged unauthenticated requests, and the operator
panel loaded in an authenticated browser. A live authenticated forged-header
request was not performed. Rollback evidence includes a prior live rollback,
an isolated current-release symlink rehearsal and a guarded final-wheel cutover.
Inert server files and older releases remain until their rollback window ends;
unrelated remote-support key rotation is scheduled separately.

## After 0.1.0

Add a dedicated settings menu for panel and AWG configuration. This is a
follow-up feature and does not expand the current release gate.

Schedule separate maintenance for rotation of the unrelated remote-support
server identity. Its private key permissions have been restricted; rotating it
requires coordinating client trust updates and is outside this release.
