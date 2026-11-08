# P6 Source Audit and Implementation Plan v1.1

**Status:** P6 IMPLEMENTATION COMPLETE
**Supersedes:** v1.0

## 1. Entry Sequence

```text
P6 v1.1 document-set acceptance
→ verify/materialize exact NSL source checkout
→ P6-CA01 source-backed contract closure
→ P6-S0 AE Runtime Worker
→ P6-S1 Dispatcher / Runtime Operations
→ P6-S2 Skill Artifact Gateway
→ P6-S3 Request / Identity Binding
→ P6-S4 LOCAL_SKILL Executor
→ P6-S5 NSL READ Backend Integration
→ P6-S6 Result / Timeline Integration
→ P6-S7 E2E-01 IA READ Closure
```

P6-CA01 and P6-S0 through P6-S7 are closed by their matching transition and
Slice records. No further P6 implementation Slice is authorized by this plan.

## 2. Refactoring-First Rule

Before feature work:

- inspect current AE runtime composition;
- determine whether `agent_runtime/` package separation is needed;
- preserve compatibility imports;
- avoid big-bang move;
- refactor only where worker/dispatcher/executor ownership would otherwise be unsafe.

## 3. P6-S0 — AE Runtime Worker Foundation

**Status: COMPLETE**

Implement:

- process/entrypoint;
- config validation;
- readiness;
- heartbeat;
- bounded poll loop;
- drain/shutdown;
- active claims;
- lease-safe termination;
- restart;
- explicit worker capability profile.

Startup rule:

```text
configured executor
AND implementation missing
→ startup FAIL
```

Actual PostgreSQL acceptance required.

As-Built notes:

- existing `SqlAlchemyRuntimeJobQueue` remains Agent Runtime authority;
- no new shared JobQueue or database table was introduced;
- `agent_runtime_worker.py` owns process lifecycle and injected assignment
  execution without absorbing dispatcher policy;
- the CLI admits configuration checks and P6-S1 composes the DB-backed
  assignment source, while execution remains fail-closed until P6-S4; and
- actual `nex_ae_test` acceptance passed with migration currency, one durable
  lease/attempt, persisted heartbeat, restart idempotency and zero residue.

## 4. P6-S1 — Dispatcher / Runtime Operations

**Status: COMPLETE**

Implement:

### Leadership
One DB-protected active dispatcher leader per queue.

### Fairness round
```text
bounded tenant snapshot
→ oldest runnable work + tenant_id
→ one visit per tenant/round
→ per-tenant cap
→ global cap
→ rebuild next round from DB
```

### Capability-aware atomic claim
Claim candidate query/update SHALL join/resolve `ExecutableStep.executor_kind` and apply worker capability eligibility before lease CAS succeeds.

### Backpressure
Define exact config and API behavior for:

- global active cap;
- per-tenant cap;
- dispatch batch;
- worker concurrency;
- max runnable depth;
- reject-or-delay admission.

### Tests
- leader exclusivity;
- failover/standby;
- two/three tenant fairness;
- continuously noisy tenant;
- unsupported executor cannot be leased;
- lease reclaim;
- delayed/dead-letter;
- caps/backpressure;
- bounded operational metric emission; and
- AG protected read access without RuntimeJob mutation authority.

As-Built notes:

- migration `2200_ae_runtime_dispatch` adds the short-named durable leader
  lease and malformed-job issue tables plus runnable/executor indexes;
- the leader lease uses a monotonic fencing token and all leader-owned claims
  re-check that token in the capability-aware lease CAS transaction;
- `DELAY` rejects admission with retryable
  `ae.runtime_job_backpressure_delayed` plus `retry_after_seconds`; `REJECT`
  uses retryable `ae.runtime_job_backpressure_rejected`;
- malformed runnable jobs are dead-lettered with a bounded reason ledger;
- AG receives only bounded aggregate GET data and no mutation authority; and
- actual `nex_ae_test` acceptance passed all 19 checks with zero residue.

## 5. P6-S2 — Skill Artifact Gateway

**Status: COMPLETE**

After CA01 schemas.

Implement:

```text
exact skill/version
→ exact package
→ existing NSL verification/trust
→ semantic binding
→ VerifiedSkillArtifact
```

No crypto duplication in AE.

Production profile rejects unsigned/untrusted package.

As-Built notes:

- `skill_artifacts.py` uses a structural port compatible with the public NSL
  v0.1 verified-package resolver and does not duplicate package cryptography;
- exact selector, semantic hash, package hash, signer, trust policy, evidence,
  and admission identities are rechecked fail-closed;
- shared canonical semantic hashes produce the bounded transition artifact;
- migration `2201_ae_nsl_artifact` persists immutable tenant-scoped artifact
  projections and no package/signature bytes or verification journal; and
- actual `nex_ae_test` acceptance passed all 14 checks with zero residue.

## 6. P6-S3 — NSLStepExecutionBinding + Request

**Status: COMPLETE**

Create durable AE-owned binding before backend call.

Recommended migration/table:

```text
ae_nsl_step_execution
```

Required uniqueness:

```text
UNIQUE (tenant_id, executable_step_id)
```

Persist:

```text
NSLExecutionId
BusinessOperationId
exact skill/version/hash
artifact/trust refs
request hash
backend profile
state/result refs
```

Implement `SkillExecutionRequest`.

Implement StepResult reader/writer evolution to schema 1.2.

As-Built notes:

- migration `2202_ae_nsl_step_execution` adds the short-named binding table,
  step cardinality and runtime-ID uniqueness, bounded JSON identity checks,
  and additive StepResult 1.2 storage support;
- `nsl_step_executions.py` validates and persists one canonical request and
  context projection while rejecting full AgentContext/private material;
- exact tenant, ExecutableStep, AgentContext, Skill/version and verified
  artifact lineage is checked before the binding transaction commits;
- restart/retry reloads the same NSL execution and BusinessOperation IDs, and
  any changed immutable request fails closed;
- historical StepResult 1.1 remains unchanged; StepResult 1.2 requires a
  BusinessOperation ID only for `LOCAL_SKILL`; and
- actual `nex_ae_test` acceptance passed all 20 checks with zero residue.

## 7. P6-S4 — LOCAL_SKILL Activation

**Status: COMPLETE**

Extend capability snapshot/compiler/executor registry:

```text
step_type = LOCAL_SKILL
executor_kind = LOCAL_SKILL
```

Register only when all dependencies are available:

- artifact gateway;
- binding repository;
- request builder;
- selected backend;
- result mapper.

No direct Plan→NSL.

As-Built notes:

- P5-only snapshots/plans remain schema 1.1, while exact `LOCAL_SKILL`
  snapshots/plans use additive schema 1.2 and compiler `p6.1`;
- the compiled step persists an exact Skill/version/semantic/runtime/trust/
  package/backend binding;
- registry construction rejects partial dependencies, raw local executor
  injection, backend-profile drift, and invalid runtime binding state;
- the worker check consumes executor kinds and backend profiles from the
  composed registry rather than a parallel declaration;
- migration `2203_ae_local_skill_activation` adds no table and preserves
  historical P5 rows; and
- actual `nex_ae_test` acceptance passed all 19 checks with zero residue and
  proved that S4 does not invoke the backend.

## 8. P6-S5 — NSL READ Backend Integration

**Status: COMPLETE**

Canonical Slice name is version-neutral.

Implement:

```text
NSLReadBackend
```

Initial backend:

```text
V01ReadBackendAdapter
```

Use stable `nsl.api` contracts.

Backend selection is explicit configuration, not silent auto-detection.

Selected CA01 process profile must prove crash/timeout containment.

As-Built:

- `NSLReadBackend` and explicit `V01ReadBackendAdapter` map the durable P6
  request/context/artifact bundle to stable `nsl.api` job fields;
- `V01ProcessEntrypoint` runs the v0.1 worker in the selected spawned-process
  boundary and bridges ordered progress plus audit/snapshot evidence;
- timeout, crash, target and malformed-protocol failures are contained and
  persisted without leaking child exception text;
- immutable attempt evidence is stored in `ae_nsl_backend_run`, while existing
  queue, lease and request-binding authorities remain unchanged;
- actual `nex_ae_test` acceptance executed exact clean NSL revision
  `803f22aadc3946a48b05472c80b60fe11d9d9554` and the signed golden READ with
  zero residue; and
- S5 did not create result-summary, StepResult or timeline state. Those were
  assigned to and completed by P6-S6.

## 9. P6-S6 — Result / Timeline Integration

**Status: COMPLETE**

Implement:

```text
RuntimeResultEnvelope or native result
→ NSLResultSummary
→ StepExecutionOutcome
→ StepResult v1.2
```

Timeline:

- reconstruct from canonical records/evidence;
- deterministic ordering key;
- versioned phase/source order;
- no inferred unavailable state;
- projection-gap metadata;
- no raw content.

Do not add timeline SoR unless source audit proves a required event cannot be represented.

As-Built:

- terminal `RuntimeResultEnvelope` evidence is mapped into a bounded
  `NSLResultSummary`, stable `StepExecutionOutcome` and durable LOCAL_SKILL
  `StepResult v1.2`;
- exact replay is idempotent while changed terminal summary evidence fails
  closed;
- P5 StepResult schema 1.1 behavior remains unchanged;
- the timeline is a deterministic protected read projection over existing
  AgentExecution, plan/step, RuntimeJob/attempt, NSL binding/run, StepResult,
  AgentResult and ResultDelivery records;
- missing historical transitions and v0.1 progress timestamps are explicit
  projection gaps;
- source audit proved migration `2205` and a separate timeline SoR are not
  required; and
- actual `nex_ae_test` acceptance passed 20/20 checks with 21 projected events,
  restart determinism and zero residue.

## 10. P6-S7 — E2E-01 IA READ Closure

**Status: COMPLETE**

Protected PostgreSQL journey:

1. IA prompt/AgentExecution;
2. WorkIntent/Context/Plan;
3. LOCAL_SKILL compile;
4. RuntimeJob enqueue;
5. dispatcher leader selects tenant;
6. capability-aware atomic claim;
7. exact verified Skill artifact;
8. durable NSLStepExecutionBinding;
9. canonical SkillExecutionRequest;
10. NSL READ execution;
11. NSLResultSummary;
12. StepResult v1.2;
13. dependent/finalization steps;
14. AgentResult;
15. ResultDelivery remains PENDING;
16. timeline reconstruction;
17. restart/dedup;
18. zero residue.

Closure also proves v0.1 external AE gaps for actual dispatch/consume and deterministic-result separation.

As-Built:

- a canonical S7 handler composes exact artifact resolution, durable request
  binding, process-isolated NSL READ and bounded result integration;
- the DB-protected dispatcher and bounded Agent Runtime worker consume the
  LOCAL_SKILL RuntimeJob, while the existing P5 worker executes the dependent
  deterministic report;
- the existing finalization authority persists one AgentResult and one
  required PENDING ResultDelivery atomically;
- restart replay preserves result IDs/hashes and timeline output, while a
  completed RuntimeJob is not dispatched again;
- actual PostgreSQL/source-backed evidence passed 23/23 checks and cleaned all
  Slice rows; and
- no S7 migration was required.

## 11. Recommended Migrations

Current inventory:

```text
2200 runtime worker/dispatcher indexes/operational support
2201 verified NSL Skill artifact
2202 NSL step execution binding + StepResult schema 1.2 support
2203 LOCAL_SKILL capability/compiler/executable-step activation
2204 process-isolated NSL backend attempt evidence
2205 NOT REQUIRED: P6-S6 projects from existing canonical records/evidence
```

No cross-service FK.

## 12. Rollout

Candidate configuration:

```text
NEX_AE_AGENT_WORKER_MODE=disabled|enabled
NEX_AE_LOCAL_SKILL_MODE=disabled|shadow|required
NEX_AE_NSL_READ_BACKEND=v01|v02
```

Shadow mode SHALL NOT duplicate live NSL Tool execution for comparison.

## 13. Rollback

```text
LOCAL_SKILL disabled
→ P5 behavior remains available
```

Migrations remain additive/backward-readable.

## 14. Exit

P6 is complete only after source-backed CA01 plus S0–S7 evidence demonstrate stable identities, fair dispatch, capability-safe claims, verified artifact admission, real NSL READ execution, StepResult v1.2, deterministic timeline and P5 regression PASS.
