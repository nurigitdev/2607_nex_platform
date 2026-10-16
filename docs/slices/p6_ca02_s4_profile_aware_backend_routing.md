# P6-CA02-S4 Profile-Aware Backend Routing

**Status:** COMPLETE
**Date:** 2026-10-16
**Predecessor:** P6-CA02-S3 In-Process NSL READ Backend Adapter
**Next:** Worker composition, readiness evidence, and default profile activation

## Purpose

This Slice connects the dual-profile persistence contract from S2 to the
in-process and process-isolated backend implementations through one exact,
fail-closed resolver.

```text
durable NSLStepExecutionBinding.backend_profile
-> NSLReadBackendRouter.resolve(exact profile)
-> matching NSLReadBackend
-> backend run with the same profile
```

No database schema, runtime identity, request, result, retry, or lease contract
changed.

## Routing Boundary

`NSLReadBackendRouter` owns an immutable-in-practice profile-to-backend map at
runtime composition time. Construction fails when:

- no backend is configured;
- a route key is not a supported profile;
- a backend does not implement the `NSLReadBackend` contract; or
- the route key and backend-declared profile differ.

Resolution uses only the exact durable profile. A supported but unconfigured
profile returns retryable `ae.nsl_backend_profile_unavailable`; an unknown
profile returns `ae.nsl_backend_profile_unsupported`. Neither condition falls
back to another backend.

`NSLReadExecutionService` now:

- accepts either one historical backend or the profile-aware router;
- resolves from the persisted binding before invocation;
- compares the compiled expected profile with the persisted profile;
- rejects replay evidence whose profile differs from the binding; and
- rejects a newly returned backend run whose profile differs from the route.

The IA READ handler supplies the compiled profile as an expected invariant.
The durable binding remains the authoritative route source.

## Executor and Readiness Projection

One `P6LocalSkillExecutor` can now accept a router and expose all configured
profiles through `backend_profiles`. `P5StepExecutorRegistry` projects this
exact set to worker readiness instead of assuming one backend value.

The executor still fails closed when a compiled `LOCAL_SKILL` step requests a
profile outside that set. Dispatcher behavior from P6-S1A remains unchanged:
such work stays `QUEUED / NO_CAPABLE_WORKER` when no capable worker advertises
the profile and is not dead-lettered merely because another worker profile is
active.

## PostgreSQL Evidence

Protected smoke used the actual `nex_ae_test` database and `nex_ae_user` role.
It migrated through `2205_ae_nsl_dual_profile`, then independently persisted
and routed both profiles:

```text
NSL_V01_PROCESS_ISOLATED -> exact process-isolated probe backend
NSL_V01_IN_PROCESS       -> exact in-process probe backend
```

For each profile, the smoke verified durable round-trip, exact route selection,
compiled/persisted agreement, no fallback when only the other backend was
configured, restart-safe profile retention, and zero-residue cleanup.

```text
status: PASS
actual PostgreSQL: yes
checks: 5/5
latest migration: 2205_ae_nsl_dual_profile
remote provider required: no
```

## Regression and Coverage

NeX-AE Slice Gate:

```text
3864 passed, 6 protected tests skipped
statement coverage: 98.62%
branch coverage: 96.83%
S4 protected smoke scope: 100.00% statement, 100.00% branch
contract validation: PASS
schemas/examples/negative examples/OpenAPI: 174/236/204/7
```

The first gate attempt found only insufficient pytest-process coverage for the
smoke verifier; all 3,861 tests had passed. The verifier then received direct
unit coverage. The complete gate plus actual PostgreSQL smoke passed, and was
run once more after the single-backend compatibility property was restored.

## Boundary

- No new table or migration was added.
- Existing process-isolated rows are not rewritten.
- Remote model providers are not involved in NSL backend selection.
- The worker executable is not yet composed with both admitted backends.
- The configured worker default and production readiness advertisement are not
  switched in this Slice.
- Worker composition, package-readiness coupling, and controlled default
  activation remain the next Slice boundary.
