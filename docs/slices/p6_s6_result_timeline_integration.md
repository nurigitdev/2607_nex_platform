# P6-S6 Result and Timeline Integration

**Status:** COMPLETE
**Date:** 2026-10-15
**Predecessor:** P6-S5 NSL READ Backend Integration
**Next:** P6-S7 E2E-01 IA READ Closure

## Purpose

P6-S6 converts terminal, source-backed NSL READ evidence into the existing AE
result authority and exposes a deterministic execution timeline without
inventing a second event store.

```text
terminal RuntimeResultEnvelope
-> bounded NSLResultSummary
-> StepExecutionOutcome
-> StepResult v1.2
-> complete-retained-evidence timeline projection
```

P6-S6 does not finalize `AgentResult` or `ResultDelivery`; those remain in the
P6-S7 end-to-end closure.

## Source Audit

The source audit found that the required retained evidence already exists in:

- `ae_agent_execution`;
- `ae_executable_plan` and `ae_executable_step`;
- `ae_runtime_job` and `ae_runtime_job_attempt`;
- `ae_nsl_step_execution` and `ae_nsl_backend_run`;
- `ae_step_result`; and
- optional `ae_agent_result` and `ae_result_delivery` records.

Therefore migration `2205` and an independent timeline source of record were
not justified. Historical transition sequences that the current schema never
retained are emitted as explicit projection gaps instead of inferred events.

## Implementation

`nsl_result_integration.py` adds:

- exhaustive terminal v0.1 status mapping;
- bounded `NSLResultSummary` construction over binding, artifact and backend
  attempt evidence;
- exact execution, BusinessOperation, Skill, artifact and trust lineage
  checks;
- false-success rejection for timeout/crash/isolation failures;
- READ-only null preservation for future WRITE lifecycle fields; and
- conversion to a `StepExecutionOutcome` carrying the stable
  BusinessOperation ID and actual invocation timestamps.

`nsl_step_executions.py` now terminalizes a RUNNING binding with a compare and
set update. The summary reference and hash remain in the canonical
`binding_json`; no duplicate physical columns or new table were added. Exact
replay is idempotent and conflicting terminal evidence fails closed.

`multi_step_engine.py` and `step_executors.py` pass LOCAL_SKILL identity and
timing into the existing StepResult repository. P5 executors continue to
produce schema 1.1 with null operation identities; LOCAL_SKILL produces schema
1.2 with a stable non-null BusinessOperation ID and null operation
fingerprint.

`agent_execution_timeline.py` reconstructs the protected read projection with
the versioned ordering key:

```text
(event_time, phase_order, source_type_order, stable_source_id)
```

The projection contains bounded metadata and opaque evidence references, not
prompts, raw runtime envelopes, result payloads, credentials, or detailed NSL
audit journals. It records these current source limitations explicitly:

- execution transition history unavailable;
- step transition history unavailable; and
- per-progress-event NSL v0.1 timestamps unavailable.

## Persistence Decision

No migration was added.

```text
current migration count: 43
latest migration: 2204_ae_nsl_backend_run
2205 timeline projection support: NOT REQUIRED
```

`NSLResultSummary` is reproducible from immutable retained evidence and its
reference/hash are anchored in the terminal binding. `StepResult v1.2`
remains the durable platform result authority. The timeline is always rebuilt
from canonical records and receives its own deterministic projection hash.

## Verification

Focused implementation and adjacent regression:

```text
180 passed
nsl_result_integration.py + agent_execution_timeline.py:
  statement/branch combined coverage 98%
```

Actual protected source-backed PostgreSQL smoke:

```text
database: nex_ae_test
role: nex_ae_user
43 migrations current; latest 2204_ae_nsl_backend_run
exact NSL source: 803f22aadc3946a48b05472c80b60fe11d9d9554
checks: 20/20 PASS
StepResult v1.2 rows: 1
timeline events: 21
projection gaps: 3
restart-deterministic projection: PASS
remaining P6-S6/P5 rows after cleanup: 0
```

Final AE Slice Gate with the complete P6 regression set:

```text
3708 passed, 5 protected tests skipped
statement coverage: 98.66%
branch coverage: 96.88%
contract validation: PASS
  schemas=174 examples=236 negative_examples=204 openapi=7
PostgreSQL smoke: 20/20 PASS
```

No remote embedding, reranking, or generation provider was required.
