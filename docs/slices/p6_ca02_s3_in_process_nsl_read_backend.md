# P6-CA02-S3 In-Process NSL READ Backend Adapter

**Status:** COMPLETE
**Date:** 2026-10-16
**Predecessor:** P6-CA02-S2 Dual-Profile Contract and Persistence Compatibility
**Next:** In-process worker composition, readiness evidence, and default activation

## Purpose

This Slice implements the admitted `NSL_V01_IN_PROCESS` READ backend behind
the existing `NSLReadBackend` interface. It does not change the P6 request,
identity, result, persistence, or retry contracts.

```text
SkillExecutionRequest
-> V01InProcessReadBackendAdapter
-> public nsl.api
-> fresh SkillExecutionWorker session
-> NSLResultEnvelope + progress + evidence
-> existing NSL backend run contract
```

The process-isolated adapter remains available and unchanged for historical
bindings and future crash-containment profiles.

## Adapter Boundary

`V01InProcessReadBackendAdapter`:

- exposes the exact `NSL_V01_IN_PROCESS` profile;
- validates the existing request, context projection, and verified artifact;
- maps them through the existing `build_v01_skill_execution_job` contract;
- imports only `nsl.api`, never NSL private Runtime modules;
- creates a new progress sink and worker session for every execution;
- preserves `NSLExecutionId` and `BusinessOperationId` across attempts; and
- emits the same durable backend-run shape consumed by P6 result integration.

The adapter records a valid NSL terminal envelope as execution-boundary
`COMPLETED`, including NSL terminal statuses other than success. A caught NSL
target exception is recorded as `TARGET_ERROR`; malformed worker, progress,
result, or evidence contracts are recorded as `PROTOCOL_ERROR`. Exception
details do not cross the backend evidence boundary.

## Timeout and Isolation Semantics

The in-process adapter declares `NSL_COOPERATIVE_DEADLINE`. It relies on NSL
Runtime and READ-tool cooperative resource/deadline checks and does not use
`asyncio.wait_for`, a thread, or a child process to claim hard termination.

Therefore:

- a native crash or non-cooperative infinite loop is not contained by this
  profile;
- an abnormal AE worker exit is recovered through RuntimeJob lease expiry;
- hard crash/timeout containment remains the responsibility of
  `NSL_V01_PROCESS_ISOLATED`; and
- the synchronous AE worker loop is required. Invocation from an already
  running event loop fails closed as protocol evidence.

## Installed-Wheel Evidence

The admitted wheel from P6-CA02-S1 was installed into the Platform `.venv`
without dependencies and exercised through the new adapter. The protected
smoke verified that Runtime imports came from installed `site-packages`, not
the NSL source checkout.

```text
status: PASS
checks: 10/10
distribution: nex-skill-language
package version: 0.1.0
source revision: 3b4cb198888570a857e6fb0d3aa077930bb23504
wheel sha256: 290a202f540ec98291842e9281a28288cc7ac112525b6c0f02c10b8721aef21f
cryptography: 46.0.7
backend profile: NSL_V01_IN_PROCESS
sessions/executions: 2/2
remote provider required: no
```

Both executions completed with full progress and snapshot evidence. They used
fresh sessions while retaining the same NSL and business-operation identities.
The checkout supplied only the protected source fixture; it was not added to
`sys.path` and was not a Runtime import source.

## Regression and Coverage

Focused new-adapter, smoke-harness, and historical process-isolated regression:

```text
46 passed
combined changed-source coverage: 98%
```

P6 regression:

```text
285 passed, 1 protected PostgreSQL smoke skipped
```

NeX-AE Slice Gate:

```text
3840 passed, 6 protected PostgreSQL tests skipped
statement coverage: 98.61%
branch coverage: 96.82%
in-process/backend module: 98.48% statement, 98.28% branch
protected smoke harness: 99.24% statement, 95.83% branch
contract validation: PASS
schemas/examples/negative examples/OpenAPI: 174/236/204/7
```

## Boundary

- No database migration or persistence schema change was required.
- PostgreSQL and remote model providers were not required.
- No source-checkout Runtime import fallback was added.
- Worker configuration still defaults to the process-isolated profile.
- Worker readiness does not advertise the in-process profile yet.
- Readiness admission, runtime composition, and default-profile activation are
  the next Slice boundary.
