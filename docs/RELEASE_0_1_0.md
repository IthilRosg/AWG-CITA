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
   Deployment and production mutation require their own reviewed change.

## Current evidence

- Local Python suite passes on Windows; POSIX-only tests must pass in Linux CI.
- Local browser scenarios: mock UI, adapter boundary, real canary mutation, and
  one-time create/lost-response scenarios pass against synthetic fixtures.
- Isolated wheel build/install smoke test passes.
- Public safety scan passes on the current development candidate. The canary
  configuration contract is described in [CANARY_CONFIG.md](CANARY_CONFIG.md).
- The deployed server files differ from this development tree. Local tests do
  not certify the deployed revision. The installed action and relay services
  currently use loopback TCP and have no private Unix sockets or protected-peer
  profile, so deployment requires a topology migration rather than a file swap.
- Unauthenticated GETs on the current operator origin return `401` for `/`,
  `/api/clients` and `/api/status`. This is a narrow live observation, not a
  complete authorization review. The private host migration packet is kept
  outside the release candidate under `.ops-tmp/`.
