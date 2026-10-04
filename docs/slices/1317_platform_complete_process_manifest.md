# Slice 1317: Platform complete process manifest

## Outcome

- Materialized one canonical runtime manifest with six public endpoints and
  thirteen independently identified processes: five APIs, AE Web, five
  workers, and two daemons.
- Bound every API and Web process to an explicit host, port, command, probes,
  dependencies, and environment-name ownership without exposing command or
  environment values in the public projection.
- Added command-target validation and a deterministic six-layer startup plan.
- Added a signal-aware `local_mock` background process shell that imports each
  of the seven concrete runtime modules and supports coordinated start/stop.
- Added all service endpoint names, including AE Web, to protected-profile
  validation so missing topology configuration fails before process spawn.

## Decision

Workers remain separate processes rather than being merged into one owner-wide
host. This preserves independent worker identity, scaling, heartbeat, and
failure isolation.

The `local_mock` process shell proves module loading and process lifecycle but
does not claim jobs. Cross-process durable queue and handler wiring requires
the service-local PostgreSQL worker runtime and remains assigned to S133. S132
must not describe the shell as business-work execution evidence.

## Verification

- Focused regression: `29 passed`, followed by `11 passed` for defensive
  changed-scope branches.
- Slice Gate (`nex-oa`): `966 passed`, `11 skipped`; statement `98.45%`,
  branch `97.75%`.
- Process manifest, background shell, and smoke runner coverage: statement
  `100.00%`, branch `100.00%` for each scope.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Smoke summary: `6` endpoints, `13` processes, kind inventory `5/1/5/2`,
  `6` startup layers, and `next=1318`.

The protected PostgreSQL tests remain opt-in and account for the `11` skips.
No database or remote provider is contacted.
