# P6 Pre-Architecture Decision — Agent Runtime Worker, Dispatch, Replay, Timeline and LOCAL_SKILL Placement v1.0

**Status:** APPROVED PRE-P6 ARCHITECTURE BASELINE  
**Phase:** P6 — NSL v0.2 READ Integration  
**Predecessor:** P5 Agent Planning & Execution Foundation — IMPLEMENTATION COMPLETE  
**Successor:** P6 SRS / Implementation Slices  
**Target location:** `docs/transition/P6/`

## 1. Purpose

P5 completed:

```text
PROMPT
→ AgentExecution
→ WorkIntent
→ AgentContext
→ AgentPlan
→ PlanValidation
→ ExecutablePlan
→ ExecutableStep[]
→ RuntimeJob
→ StepResult[]
→ AgentResult
→ ResultDelivery(PENDING)
```

P6 introduces:

```text
ExecutableStep(LOCAL_SKILL)
→ Skill Artifact Gateway
→ VerifiedSkillArtifact
→ SkillExecutionRequest
→ NSL v0.2 READ
→ NSLResultSummary
→ StepResult
```

Before P6 implementation, the following five decisions are fixed:

1. dedicated AE Agent Runtime Worker process;
2. tenant-aware RuntimeJob dispatcher minimum policy;
3. Agent RuntimeJob retry/replay/reconciliation rules;
4. complete AgentExecution timeline / observability;
5. `LOCAL_SKILL` executor placement and ownership.

This document does not modify the Frozen Platform/Agent/NSL semantic baseline.

---

## 2. Existing Decision Preserved

```text
service_jobs / nex_runtime.JobQueue
!=
ae_runtime_job / ae_runtime_job_attempt
```

The shared JobQueue remains general service-local asynchronous work.

AE RuntimeJob remains the canonical AgentExecution / ExecutableStep progression ledger.

P6 SHALL NOT merge the tables, state vocabularies, replay semantics, or domain authority.

Shared low-level worker lifecycle primitives MAY be reused when AE RuntimeJob semantics remain intact.

---

# 3. P6-PAD-01 — Dedicated AE Agent Runtime Worker Process

## Decision

P6 SHALL introduce an independently runnable AE Agent Runtime Worker process.

The AE API process SHALL admit, observe and control Agent work, but SHALL NOT be the implicit production long-running worker fleet.

```text
AE API
  ├─ PROMPT admission
  ├─ AgentExecution / Plan creation
  ├─ RuntimeJob enqueue
  └─ operational/read APIs
          │
          ▼
     ae_runtime_job
          │
          ▼
AE Agent Runtime Worker
  ├─ claim RuntimeJob
  ├─ enforce lease
  ├─ dispatch ExecutableStep
  ├─ execute registered executor
  ├─ persist StepResult
  └─ advance AgentExecution / ExecutablePlan
```

## Mandatory lifecycle

The worker SHALL support:

- startup configuration validation;
- startup readiness;
- bounded polling;
- graceful drain;
- SIGTERM/shutdown handling;
- worker heartbeat;
- active-claim accounting;
- lease-safe termination;
- restart recovery;
- structured logging;
- bounded concurrency;
- zero raw prompt/result/credential logging.

## Shared primitive reuse

P6 MAY reuse:

```text
worker lifecycle
heartbeat helper
signal handling
structured logging
drain helper
bounded polling helper
```

but SHALL NOT reuse `service_jobs` as Agent execution authority.

## Source ownership

Recommended:

```text
services/nex-ae-api/nex_ae_api/agent_runtime/
  worker.py
  dispatcher.py
  scheduler.py
  executors/
  observability.py
```

A large source refactor is not mandatory; compatibility facades are acceptable.

## Acceptance

Actual PostgreSQL evidence SHALL prove:

```text
start
→ heartbeat
→ claim RuntimeJob
→ execute eligible step
→ complete/fail under lease authority
→ drain
→ restart and reclaim eligible work
```

---

# 4. P6-PAD-02 — Tenant-Aware Dispatcher Minimum Policy

## Decision

P6 SHALL add a tenant-aware dispatcher in front of `RuntimeJob.claim()`.

Minimum policy:

```text
discover runnable tenants
→ deterministic bounded round-robin
→ per-tenant concurrency limit
→ global concurrency limit
→ claim one RuntimeJob
```

P6 SHALL NOT build a general-purpose scheduler.

## Fairness

Fairness SHALL be tenant/system-policy based.

It SHALL NOT use user-supplied priority, prompt text, principal name or client urgency.

Initial policy:

```text
global_worker_concurrency = bounded configuration
per_tenant_concurrency    = bounded configuration
tenant_selection          = deterministic round-robin
```

## Runnable tenant discovery

P6 SHALL provide a protected/internal query equivalent to:

```text
state = QUEUED AND run_after <= now
OR
state = RUNNING AND lease_until < now
```

Tenant results SHALL be bounded and deterministically ordered.

## Backpressure

At minimum:

- global queue-depth guard;
- per-tenant active-claim guard;
- worker concurrency bound;
- overload rejection or delayed admission;
- delayed-job handling;
- expired-lease reclaim;
- dead-letter isolation.

## Executor routing

Workers MAY declare supported executor kinds.

Example:

```text
worker-A: CANONICAL_CAPABILITY, REPORT, LOCAL_SKILL
worker-B: CANONICAL_CAPABILITY, REPORT
```

P6 closure MAY use homogeneous workers.

## Metrics

High-cardinality PrincipalId, AgentExecutionId, RuntimeJobId and StepId SHALL NOT be general metric labels.

## Acceptance

P6 SHALL prove:

- bounded no-starvation multi-tenant behavior;
- per-tenant concurrency respected;
- global concurrency respected;
- expired lease reclaimable;
- one noisy tenant cannot consume every worker slot.

---

# 5. P6-PAD-03 — Agent RuntimeJob Retry, Replay and Reconciliation

## Decision

```text
Common Job replay
!=
Agent Runtime replay
```

An operator SHALL NOT create a new RuntimeJob merely to "run the same ExecutableStep again".

## Allowed continuation mechanisms

Agent Runtime progression may occur only through a canonical reason:

```text
technical retry
resume after wait
reconciliation
explicit replan / new plan version
later publication retry
```

## P6 READ retry

For `LOCAL_SKILL / NSL READ`:

```text
same AgentExecutionId
same ExecutablePlanId
same ExecutableStepId
same NSLExecutionId when required by Frozen integration semantics
bounded RuntimeJob retry
append-only attempt history
```

Technical retry is not semantic replan.

## Blind replay prohibited

Forbidden:

```text
FAILED RuntimeJob
→ arbitrary new RuntimeJob
→ same step execution
```

Required:

```text
inspect AgentExecution / Step / RuntimeJob state
→ select allowed policy action
→ runtime creates canonical continuation/retry/reconciliation work
```

## Future WRITE safety

P6 SHALL NOT introduce a replay API that would later violate:

```text
UNKNOWN_COMMIT_STATE
!=
ordinary RuntimeJob failure
```

## Dead letter

`DEAD_LETTER` means automated retry is exhausted.

It does NOT authorize blind operator replay.

## Acceptance

Tests SHALL prove:

- retry stays in the same execution/step lineage;
- attempt history is append-only;
- stale lease completion is rejected;
- arbitrary Agent Runtime replay entrypoint does not exist;
- dead-letter review does not execute a step.

---

# 6. P6-PAD-04 — Complete AgentExecution Timeline

## Decision

P6 SHALL replace the P4-era single-job trace assumption with a complete ordered AgentExecution timeline.

The timeline is a protected read/operational projection, not a new SoR.

## Timeline scope

```text
ExecutionTrigger
WorkIntent
AgentContext
AgentPlan
PlanValidation
ExecutablePlan
RuntimeJob / Attempt
ExecutableStep
StepResult
...
AgentResult
ResultDelivery
```

P6 adds, when present:

```text
VerifiedSkillArtifact
NSLExecutionId
NSLResultSummary
```

## Minimum event projection

```text
sequence
event_time
event_type
tenant_id
correlation_id
agent_execution_id

runtime_job_id?
runtime_attempt_no?
executable_plan_id?
compiled_step_key?
executable_step_id?
step_result_id?

nsl_execution_id?
skill_ref?
skill_version?

state_before?
state_after?
phase?
outcome?
error_ref?

evidence_refs[]
```

Raw prompt/response/document content, secrets, credentials, provider endpoint and DB URL are forbidden.

## Source of truth

Timeline SHALL be reconstructed from canonical persisted records/projections.

It SHALL NOT become an independently editable authoritative log.

## Minimum operational metrics

```text
queued / running / retrying / failed / dead-letter
oldest runnable age
claim latency
step latency
execution latency
lease expiry count
stale completion rejection count
reclaim count
worker heartbeat
active claims
drain state
capacity saturation
throughput/failure by bounded agent/executor/job type
```

## AG boundary

NeX-AG MAY consume protected AE operational APIs/projections.

NeX-AG SHALL NOT claim RuntimeJobs or mutate AE Runtime tables.

## Acceptance

P6 SHALL show one ordered timeline containing:

```text
planning
→ normal P5 step
→ LOCAL_SKILL / NSL READ step
→ StepResult
→ AgentResult
```

---

# 7. P6-PAD-05 — LOCAL_SKILL Executor Placement

## Decision

`LOCAL_SKILL` is an AE Step Executor type owned by the NeX-AE Agent Runtime.

It is NOT owned by NSL.

```text
StepExecutionEngine / AE Worker
        │
        ▼
LOCAL_SKILL Executor
        ├─ construct SkillExecutionRequest
        ├─ resolve exact skill/package
        ├─ call Skill Artifact Gateway
        ├─ obtain VerifiedSkillArtifact
        ├─ invoke NSL Runtime
        ├─ receive NSLResultSummary
        └─ map to StepResult
```

## Responsibility boundary

### AE owns

- AgentExecution
- ExecutablePlan
- ExecutableStep
- scheduling
- LOCAL_SKILL executor
- capability binding
- SkillExecutionRequest construction
- context/identity projection
- retry/wait/reconciliation orchestration
- StepResult
- AgentResult

### Skill Artifact Gateway owns

- exact skill/version resolution
- package retrieval
- signature/trust verification
- VerifiedSkillArtifact

### NSL Runtime owns

- deterministic NSL execution
- NSLExecutionId semantics
- READ semantics
- runtime limits
- NSL tool invocation
- CHECK / EMIT behavior
- NSL evidence/result
- later WRITE idempotency/commit/verification semantics

## No direct Plan-to-NSL call

Forbidden:

```text
Plan Builder
→ NSL directly
```

Required:

```text
AgentPlan
→ Plan Validator
→ Deterministic Compiler
→ ExecutableStep(type=LOCAL_SKILL)
→ StepExecutionEngine
→ LOCAL_SKILL Executor
→ NSL
```

## Context projection

The LOCAL_SKILL executor SHALL NOT copy the full AgentContext into NSL.

It SHALL build the exact `SkillExecutionRequest` projection required by the Frozen Agent↔NSL Integration Contract.

Applicable READ fields include:

```text
agent_execution_id
executable_plan_id
executable_step_id
nsl_execution_id
tenant
exact skill/version
compiled inputs
resource refs
principal/business actor
role bindings
org/project/classification refs
correlation_id
causation_id
context ref/hash
mode
```

WRITE-specific fields remain absent/null per the P6 READ contract.

## Registration

P6 SHALL register `LOCAL_SKILL` only when all dependencies exist:

```text
Skill Artifact Gateway
VerifiedSkillArtifact validator
NSL runtime adapter
result mapper
```

Partial registration/fall-through is prohibited.

## Retry

The executor SHALL NOT perform hidden unbounded retries.

Retry authority remains in Agent Runtime + NSL integration policy.

## Acceptance

P6 SHALL prove:

```text
LOCAL_CAPABILITY
→ exact capability binding
→ LOCAL_SKILL ExecutableStep
→ exact skill/version
→ VerifiedSkillArtifact
→ NSL READ
→ NSLResultSummary
→ immutable StepResult
```

without changing P5 core identities.

---

# 8. Recommended P6 Slice Order

```text
P6-S0  AE Runtime Worker Foundation
P6-S1  Tenant Dispatcher + Runtime Operations Base
P6-S2  Skill Artifact Gateway / VerifiedSkillArtifact
P6-S3  SkillExecutionRequest Adapter
P6-S4  LOCAL_SKILL Executor
P6-S5  NSL v0.2 READ Runtime Integration
P6-S6  NSLResultSummary → StepResult + Timeline
P6-S7  E2E-01 IA READ Closure
```

P6-S0/S1 are runtime operational prerequisites.

P6-S2~S6 implement NSL READ integration.

P6-S7 closes one real end-to-end IA READ scenario.

---

# 9. P6 Entry Gate

P6 SRS SHALL preserve all of the following:

- dedicated AE Runtime Worker process boundary;
- shared JobQueue separate from AE RuntimeJob;
- bounded tenant-aware dispatcher;
- no blind Agent Runtime replay;
- complete execution timeline;
- AE-owned LOCAL_SKILL executor;
- no direct Plan→NSL invocation;
- exact Skill Artifact verification before NSL execution;
- no full AgentContext copy into NSL;
- P5 identities reused without rename.

---

# 10. Non-Goals

This decision does not implement:

- CA / PA / EA admission;
- WC;
- DELEGATE_WORK;
- NSL WRITE;
- approval;
- Enterprise OS WRITE;
- BusinessOperationId;
- UNKNOWN_COMMIT_STATE reconciliation;
- ResultDelivery publication/ACK;
- WA;
- Schedule;
- general autoscaling platform.

---

# 11. Closure Statement

```text
Shared JobQueue
≠
AE RuntimeJob

AE API
→ admission / observation

AE Runtime Worker
→ tenant-aware dispatch
→ lease-safe RuntimeJob execution
→ StepExecutionEngine

LOCAL_SKILL
→ AE-owned executor
→ Skill Artifact Gateway
→ VerifiedSkillArtifact
→ NSL v0.2 READ
→ StepResult

Operator replay
→ no blind Job recreation

Observability
→ complete AgentExecution timeline
```

> **P6 Pre-Architecture Decision v1.0 — APPROVED**
