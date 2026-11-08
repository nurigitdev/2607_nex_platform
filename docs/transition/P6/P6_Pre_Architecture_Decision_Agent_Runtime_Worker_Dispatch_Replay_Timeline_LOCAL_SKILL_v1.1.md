# P6 Pre-Architecture Decision — Agent Runtime Worker, Dispatch, Replay, Timeline and LOCAL_SKILL Placement v1.1

**Status:** P6-CA01 SOURCE-BACKED ARCHITECTURE BASELINE
**Supersedes:** v1.0
**Phase:** P6 — NSL READ Integration

## PAD-01 — Dedicated AE Runtime Worker

P6 uses a dedicated AE Runtime Worker process. AE API admits/observes work but is not the production worker fleet.

Worker lifecycle SHALL include readiness, heartbeat, bounded polling, graceful drain, signal handling, active-claim accounting, lease-safe shutdown, restart recovery, bounded concurrency and privacy-safe logging.

Shared worker lifecycle primitives MAY be reused. Shared `service_jobs` SHALL NOT become Agent execution authority.

## PAD-02 — Worker Capability Declaration

Initial P6 uses one homogeneous worker pool per deployed capability profile. Each worker declares supported executor kinds at startup. A worker configured for `LOCAL_SKILL` without an implementation fails startup. Unknown executor kinds fail closed.

## PAD-03 — Capability-Aware Atomic Claim

Required property:

```text
candidate selection
+ executor capability eligibility
+ lease compare-and-set
= one database transaction
```

P6-S1 SHALL filter the referenced `ExecutableStep.executor_kind` before the lease update succeeds.

## PAD-04 — Single Dispatcher Fairness Authority

One active dispatcher leader exists per AE Runtime queue. Leadership uses a DB-backed lease, advisory lock or equivalent single-active mechanism.

One dispatch round:

1. read a bounded runnable-tenant snapshot;
2. sort by oldest runnable work then stable `tenant_id`;
3. visit each tenant at most once;
4. claim no more than configured per-tenant amount;
5. stop at global capacity;
6. rebuild the next round from DB state.

No in-memory cursor is business authority.

## PAD-05 — Backpressure

Bound at least:

```text
global active claims
per-tenant active claims
dispatch batch size
worker concurrency
maximum runnable queue depth
delayed/dead-letter retention by policy
```

API admission uses an explicit reject-or-delay policy when capacity limits are hit.

## PAD-06 — Agent Runtime Replay Is Not Common Job Replay

```text
Common Job replay != Agent Runtime replay
```

Blind operator recreation of the same step job is prohibited. Allowed semantic continuations are bounded technical retry, wait/resume, reconciliation, explicit replan, and later publication retry.

## PAD-07 — P6 READ Identity Binding

Every LOCAL_SKILL READ step has one AE-owned durable `NSLStepExecutionBinding`:

```text
UNIQUE (tenant_id, executable_step_id)
```

Before the first backend call AE persists:

- NSLExecutionId;
- BusinessOperationId;
- exact skill/version/semantic identity;
- verified artifact ref/hash;
- request authority/hash;
- backend profile.

Technical retry/restart reuses the binding.

## PAD-08 — NSLExecutionId Responsibility Split

AE Integration allocates and persists NSLExecutionId before backend invocation and preserves it across retry/reclaim/restart.

NSL Runtime validates/consumes the ID and owns deterministic runtime lifecycle semantics associated with it.

Initial v0.1 mapping:

```text
P6 NSLExecutionId
→ SkillExecutionJob.execution_id
```

## PAD-09 — READ BusinessOperationId

BusinessOperationId is required in P6 READ. It is a stable semantic operation/correlation identity, not WRITE authority.

```text
business_operation_id = stable non-null
operation_fingerprint = null
```

BusinessOperationId is therefore not a P6 non-goal.

## PAD-10 — LOCAL_SKILL Placement

```text
AgentPlan
→ Validator
→ Compiler
→ ExecutableStep(LOCAL_SKILL)
→ AE StepExecutionEngine
→ AE LOCAL_SKILL Executor
→ Skill Artifact Gateway
→ VerifiedSkillArtifact
→ NSL Backend
→ NSLResultSummary
→ StepResult
```

Plan Builder SHALL NOT call NSL directly.

## PAD-11 — Artifact / Trust Boundary

AE SHALL not implement duplicate cryptographic verification. Exact skill/version/package verification uses NSL package/security capability or a stable adapter. Production NSL execution requires verified artifacts. No implicit latest.

## PAD-12 — Context Projection

Whole AgentContext copy is forbidden. NSL receives typed compiled inputs, explicit resource refs, bounded identity/authority/scope/classification and context ref/hash only.

## PAD-13 — Timeline Determinism and Reconstruction Limit

Timeline is a protected deterministic read projection over retained canonical records/evidence, not a second SoR.

Ordering:

```text
(event_time, phase_order, source_type_order, stable_source_id)
→ sequence
```

`phase_order` and `source_type_order` are versioned constants.

Do not infer unproven `state_before` or `state_after`; unavailable optional values remain null. Projection gaps are explicit.

## PAD-14 — Canonical P6 Slice Order

```text
P6-CA01A
→ P6-CA01
→ P6-S0
→ P6-S1
→ P6-S2
→ P6-S3
→ P6-S4
→ P6-S5 NSL READ Backend Integration
→ P6-S6
→ P6-S7
```

No feature Slice starts before CA01 closes.

## Non-Goals

P6 does not implement CA/PA/EA admission, WC, DELEGATE_WORK, NSL WRITE, approval, WRITE IdempotencyKey, CommitState, VerificationStatus, UNKNOWN_COMMIT_STATE reconciliation, ResultDelivery ACK, WA, Schedule or a general autoscaling control plane.
