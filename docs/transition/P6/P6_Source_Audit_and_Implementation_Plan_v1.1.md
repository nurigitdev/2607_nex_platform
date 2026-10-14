# P6 Source Audit and Implementation Plan v1.1

**Status:** P6-S0 COMPLETE; P6-S1 READY
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

P6-CA01 is closed by
`P6_CA01_Source_Backed_READ_Contract_Closure_v1.0.md`. P6-S0 is closed by
`../../slices/p6_s0_ae_runtime_worker_foundation.md`. The next implementation
Slice is P6-S1.

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
- the CLI admits configuration checks but rejects execution until P6-S1
  composes the DB-backed assignment source; and
- actual `nex_ae_test` acceptance passed with migration currency, one durable
  lease/attempt, persisted heartbeat, restart idempotency and zero residue.

## 4. P6-S1 — Dispatcher / Runtime Operations

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

## 5. P6-S2 — Skill Artifact Gateway

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

## 6. P6-S3 — NSLStepExecutionBinding + Request

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

## 7. P6-S4 — LOCAL_SKILL Activation

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

## 8. P6-S5 — NSL READ Backend Integration

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

## 9. P6-S6 — Result / Timeline Integration

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

## 10. P6-S7 — E2E-01 IA READ Closure

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

## 11. Recommended Migrations

Exact numbers follow current inventory.

Candidate:

```text
2200 runtime worker/dispatcher indexes/operational support
2201 NSL step execution binding
2202 StepResult schema 1.2 support
2203 timeline projection support only if needed
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
