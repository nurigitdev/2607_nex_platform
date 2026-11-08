# P6-CA02-S2 Dual-Profile Contract and Persistence Compatibility

**Status:** COMPLETE
**Date:** 2026-10-16
**Predecessor:** P6-CA02-S1 NSL Dependency Compatibility and Wheel Admission
**Next:** In-process NSL backend adapter and readiness activation

## Purpose

This Slice makes the P6 durable runtime contracts understand both NSL v0.1
profiles without reinterpreting historical data:

```text
new compile default -> NSL_V01_IN_PROCESS
historical binding  -> NSL_V01_PROCESS_ISOLATED
durable profile     -> exact worker/backend selection
unknown/missing     -> fail closed
```

It does not implement or advertise the in-process backend. Until that backend
passes readiness in a later Slice, new in-process jobs remain `QUEUED` for an
in-process-capable worker. They are never dispatched to the process-isolated
backend as a fallback.

## Contract

`nsl_backend_profiles.py` is the canonical profile catalog. It defines the two
admitted profile IDs and makes `NSL_V01_IN_PROCESS` the default for newly built
LOCAL_SKILL capabilities. Validation accepts only these exact values; whitespace,
unknown revisions and future profile names fail closed.

The transition JSON Schema now accepts both profiles. The historical Golden
READ example intentionally remains `NSL_V01_PROCESS_ISOLATED`, proving that the
existing contract remains readable rather than being rewritten to the new
default.

## Persistence

Migration `2205_ae_nsl_dual_profile` replaces only the profile CHECK constraint
on `ae_nsl_step_execution`:

- existing rows are not updated or backfilled;
- newly activated LOCAL_SKILL steps persist the exact profile from their
  compiled `skill_binding_json`;
- legacy pre-activation P6 bindings retain the process-isolated profile;
- replay or restart rejects a profile rewrite as an immutable conflict; and
- backend run records accept either admitted profile while execution services
  require the configured backend to match the durable binding exactly.

No new table was required.

## Dispatch Safety

The RuntimeJob claim path now filters LOCAL_SKILL candidates by both executor
kind and the profile stored in the executable step. The selected profile is
carried in `RuntimeJobClaim` and `AgentRuntimeAssignment`.

Consequences:

- a process-isolated worker skips in-process jobs without claiming them;
- an in-process worker skips historical process-isolated jobs;
- unsupported but known-profile work remains queued as `NO_CAPABLE_WORKER`
  behavior rather than being dead-lettered; and
- executor and backend composition re-check the compiled binding before any
  NSL invocation.

## PostgreSQL Evidence

Protected smoke ran against the actual `nex_ae_test` database as
`nex_ae_user`:

```text
status: PASS
checks: 9/9
migrations: 44 planned, 1 applied, 43 already current
latest migration: 2205_ae_nsl_dual_profile
profiles: NSL_V01_IN_PROCESS + NSL_V01_PROCESS_ISOLATED
cleanup residue: 0 for both profile runs
remote provider required: no
```

Each profile completed a separate durable binding write, idempotent replay,
repository restart read, immutable conflict check and cleanup. PostgreSQL
catalog inspection also confirmed the dual-profile CHECK constraint.

## Regression and Coverage

Focused dual-profile and affected P6 regression:

```text
119 passed
```

NeX-AE Slice Gate:

```text
3824 passed, 6 protected PostgreSQL tests skipped
statement coverage: 98.64%
branch coverage: 96.84%
contract validation: PASS
schemas/examples/negative examples/OpenAPI: 174/236/204/7
```

All changed Python source scopes met the independent 95% statement and 94%
branch thresholds. The lowest changed-source branch result was 94.51% for
`nsl_step_executions.py`.

A manually composed P5/P6-only run passed its 352 selected tests but produced
an invalid 18.08% service-wide coverage measurement because it measured the
whole AE package against only the narrow selection. It was discarded and
replaced by the canonical Slice Gate above.

## Boundary

- No in-process NSL adapter is implemented in this Slice.
- No worker advertises in-process readiness by default yet.
- The process-isolated backend and all historical evidence remain supported.
- No remote embedding, reranking or generation provider was used.
- The unchanged Full Gate remains the rollback verification path.
