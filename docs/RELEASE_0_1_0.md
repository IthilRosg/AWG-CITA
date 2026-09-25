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
- A versioned development candidate is installed on the operator host. The
  application and relay use private Unix sockets; the protected original peer
  profile and action audit are installed with restricted permissions. The
  precise host, artifact digest, baseline and rollback evidence remain in the
  private migration packet under `.ops-tmp/`.
- A read-only Playwright smoke check loaded the installed panel assets through
  the private relay and confirmed real-canary mode and one live peer. Public
  unauthenticated requests, including requests with a forged operator header,
  returned `401` on the tested page, API and static routes.
- An isolated copy of the installed Caddy operator block rejected an
  unauthenticated request and replaced a forged identity header with the
  authenticated test account before forwarding. This does not replace an
  authenticated end-to-end check of the live public route.
- Reachable Git history and the intended public file set were scanned for
  embedded credentials, private-key files, host-specific markers and large or
  binary artifacts. Flagged assignments were synthetic test fixtures. The
  server's protected configuration and backup remain private. Production
  create/enable/disable/delete, audit reconciliation, rollback and final
  cleanup remain open gates before publishing `0.1.0`.

## After 0.1.0

Add a dedicated settings menu for panel and AWG configuration. This is a
follow-up feature and does not expand the current release gate.
