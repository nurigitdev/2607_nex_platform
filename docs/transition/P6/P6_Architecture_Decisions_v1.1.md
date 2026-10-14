# P6 Architecture Decisions v1.1

**Status:** P6-CA01A CONSOLIDATED DESIGN BASELINE
**Supersedes:** v1.0

## P6-DEC-01 — Version-neutral phase name
P6 is **NSL READ Integration**.

```text
backend now      = NSL v0.1
target contract  = Frozen NSL v0.2 READ-compatible subset
```

## P6-DEC-02 — AE-facing contract targets v0.2 semantics
Canonical AE request is `SkillExecutionRequest`. The initial v0.1 adapter translates it to current `SkillExecutionJob`/`ExecutionRequest`.

## P6-DEC-03 — Identity non-collapse
```text
AgentExecutionId != ExecutableStepId != NSLExecutionId != BusinessOperationId
```

## P6-DEC-04 — AE allocates invocation identities
AE Integration allocates and durably binds `NSLExecutionId` and `BusinessOperationId` before the first backend invocation.

NSL Runtime owns lifecycle semantics for the supplied NSLExecutionId.

## P6-DEC-05 — One logical NSL execution per LOCAL_SKILL step in P6
```text
UNIQUE (tenant_id, executable_step_id)
```
Retry/reclaim/restart reuses the same binding. Replan/new ExecutableStep creates new identities.

## P6-DEC-06 — BusinessOperationId exists for READ
For READ, BusinessOperationId is a semantic operation/correlation identity only. It is not WRITE authority.

## P6-DEC-07 — StepResult semantic schema 1.2
Historical P5 v1.1 remains immutable.

P6 v1.2:
```text
non-NSL:
  business_operation_id = null
  operation_fingerprint = null

LOCAL_SKILL READ:
  business_operation_id = required non-null
  operation_fingerprint = null
```

## P6-DEC-08 — Dedicated AE worker
NSL execution happens from a dedicated AE Runtime Worker, outside the API request thread.

## P6-DEC-09 — Shared JobQueue remains separate
```text
service_jobs != ae_runtime_job
```
Shared lifecycle helpers may be reused; Agent RuntimeJob authority remains AE-owned.

## P6-DEC-10 — Homogeneous initial worker pool
Initial P6 uses one homogeneous worker pool per deployed capability profile. Workers declare executor capabilities at startup and fail closed on unsupported configured executors.

## P6-DEC-11 — Capability-aware atomic claim
RuntimeJob claim eligibility and lease CAS occur in one transaction, including referenced `ExecutableStep.executor_kind` compatibility.

## P6-DEC-12 — Single active dispatcher leader
One database-protected dispatcher leader owns fairness for each AE Runtime queue. Standby processes do not keep independent fairness authority.

## P6-DEC-13 — Deterministic bounded fairness
Each dispatch round orders runnable tenants by oldest runnable work then `tenant_id`, visits each at most once, applies per-tenant/global caps and rebuilds from DB state next round.

## P6-DEC-14 — Explicit backpressure
Global/per-tenant active claims, batch size, worker concurrency, runnable queue depth and retention are bounded. API admission follows explicit reject-or-delay policy.

## P6-DEC-15 — No blind Agent Runtime replay
Dead-letter does not authorize replay. Runtime continuation requires a canonical semantic reason.

## P6-DEC-16 — LOCAL_SKILL executor is AE-owned
AE owns scheduling, request projection, backend invocation orchestration and StepResult. NSL owns deterministic Skill execution.

## P6-DEC-17 — Exact package/version only
No implicit latest. Package/semantic identity and trust must match before runtime execution.

## P6-DEC-18 — Reuse NSL trust boundary
AE does not implement duplicate crypto. Existing NSL NSP/package verification is reused through Skill Artifact Gateway/adapter.

## P6-DEC-19 — AgentContext projection only
Whole AgentContext copy is prohibited. Only typed compiled inputs, explicit resources, bounded authority metadata and context ref/hash are supplied.

## P6-DEC-20 — v0.1 adapter is temporary but first-class
Initial backend uses stable public `nsl.api` contracts. It preserves exact semantics and may later be replaced by native v0.2 READ without changing AE identities/contracts.

## P6-DEC-21 — Conservative status mapping
Only actual NSL completion maps to successful StepResult. Tool/validation/limit failures are never converted into empty success.

## P6-DEC-22 — NSL detailed audit remains NSL evidence SoR
AE keeps stable refs/hashes/classification/minimal semantic summary, not raw journal copies.

## P6-DEC-23 — Timeline is deterministic projection, not SoR
Ordering uses versioned projection constants. Missing historical state is null, not inferred.

## P6-DEC-24 — Source-backed CA01 is mandatory before all slices
CA01A closes design consistency only. No P6 feature Slice starts until exact NSL source-backed CA01 closes.

## P6-DEC-25 — P6-S5 name is version-neutral
Canonical name:
```text
P6-S5 — NSL READ Backend Integration
```

## P6-DEC-26 — v0.2 WRITE remains fully out of scope
No partial WRITE/approval/commit/reconciliation implementation is permitted in P6.
