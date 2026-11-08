# P6 Source Audit and Implementation Plan v1.0

**Status:** PRE-IMPLEMENTATION BASELINE  
**Phase:** P6 — NSL READ Integration

---

## 1. Entry Sequence

```text
P6 document-set acceptance
→ P6-CA01 contract closure
→ P6-S0 worker
→ P6-S1 dispatcher/operations
→ P6-S2 artifact gateway
→ P6-S3 request/identity adapter
→ P6-S4 LOCAL_SKILL executor
→ P6-S5 NSL READ backend
→ P6-S6 result/timeline
→ P6-S7 E2E closure
```

S0/S1 MAY be developed after document-set acceptance, but S2+ waits for CA01.

---

## 2. Refactoring-First Rule

Before feature code:

- inspect current AE runtime composition;
- determine whether an `agent_runtime/` package boundary is needed;
- preserve compatibility imports;
- avoid a big-bang move.

Refactor only where worker/dispatcher/executor ownership would otherwise be unsafe or untestable.

---

## 3. P6-S0 — AE Runtime Worker Foundation

Implement:

- worker entrypoint/process;
- config validation;
- readiness;
- heartbeat;
- bounded poll loop;
- graceful drain;
- signal handling;
- active claim accounting;
- lease-safe shutdown;
- restart.

Reuse shared worker primitives where appropriate.

Do not move AE RuntimeJob into common JobQueue.

### Tests

- startup invalid config;
- ready/not-ready;
- graceful drain;
- SIGTERM;
- active lease shutdown;
- restart;
- zero raw payload logging.

### Gate

Actual PostgreSQL claim/complete/fail cycle.

---

## 4. P6-S1 — Tenant Dispatcher + Runtime Operations Base

Implement:

- runnable tenant discovery;
- deterministic bounded round-robin;
- per-tenant active cap;
- global active cap;
- overload/backpressure decision;
- executor-capability worker profile;
- initial worker/runtime metrics.

Potential DB change:

- indexes/projection required for efficient runnable-tenant discovery.

Do not add user-controlled priority.

### Tests

- two/three tenant fairness;
- noisy tenant;
- delayed job;
- expired lease;
- dead letter;
- global/per-tenant caps.

---

## 5. P6-S2 — Skill Artifact Gateway / VerifiedSkillArtifact

Implement after CA01.

Responsibilities:

```text
exact skill/version request
→ package lookup
→ NSL verifier/trust adapter
→ exact semantic identity
→ VerifiedSkillArtifact
```

Prefer NSL stable public APIs/security adapters.

Do not implement crypto in AE.

### Tests

- exact version;
- unknown skill;
- version mismatch;
- semantic mismatch;
- package tamper;
- unsigned production;
- wrong signer/key;
- valid signed package.

---

## 6. P6-S3 — NSL Step Execution Binding + SkillExecutionRequest

Implement AE-owned durable binding.

Recommended logical aggregate:

```text
NSLStepExecutionBinding
```

Fields:

```text
tenant_id
agent_execution_id
executable_plan_id
executable_step_id
nsl_execution_id
business_operation_id
skill_id/version/semantic_hash
verified_artifact_ref
package_trust_ref
request_hash
backend_profile
state
result_summary_ref/hash
```

Create canonical SkillExecutionRequest.

Implement:

- stable NSLExecutionId;
- stable READ BusinessOperationId;
- typed inputs;
- resources;
- principal/authority projection;
- context ref/hash;
- correlation/causation.

### StepResult Amendment

Implement controlled support for P6 LOCAL_SKILL READ:

```text
business_operation_id = required non-null
operation_fingerprint = null
```

while historical P5 results remain readable.

---

## 7. P6-S4 — LOCAL_SKILL Compiler/Executor Activation

Extend P5 capability snapshot and compiler for actual runnable LOCAL_SKILL.

Implement:

- exact NSL capability descriptor;
- `step_type=LOCAL_SKILL`;
- `executor_kind=LOCAL_SKILL`;
- executor registration;
- dependency availability guard.

No partial registration.

No direct Plan→NSL.

---

## 8. P6-S5 — NSL READ Backend Integration

Implement backend port:

```text
NSLReadBackend
```

First backend:

```text
V01ReadBackendAdapter
```

Maps canonical P6 request into stable NSL v0.1 public API.

Use:

- SkillExecutionJob;
- SkillExecutionWorker;
- RuntimeResultEnvelope;
- ToolExecutionPort;
- audit/snapshot ports;
- selected process-isolation profile.

Optional parallel work may implement a native v0.2 backend if the NSL Track is ready.

Backend selection must be explicit configuration/profile, not silent auto-detection.

### Tests

- v0.1 contract round trip;
- completion;
- validation error;
- tool error;
- limit exceeded;
- cancellation;
- crash/timeout isolation;
- same IDs on retry.

---

## 9. P6-S6 — Result Mapping + Complete Timeline

Implement:

```text
RuntimeResultEnvelope / v0.2 result
→ NSLResultSummary
→ StepExecutionOutcome
→ StepResult
```

Add complete timeline projection over:

- planning records;
- RuntimeJobs/Attempts;
- Steps/StepResults;
- NSL binding/result;
- AgentResult/Delivery.

Add protected operational metrics.

No raw content in metrics/timeline.

---

## 10. P6-S7 — E2E-01 IA READ Closure

Protected PostgreSQL scenario:

1. create/admit IA prompt;
2. produce WorkIntent/Context;
3. produce plan with LOCAL_SKILL;
4. validate/compile;
5. worker claims RuntimeJob;
6. exact signed Skill artifact verified;
7. canonical SkillExecutionRequest persisted;
8. NSL READ executes;
9. NSLResultSummary persisted/mapped;
10. StepResult persisted;
11. dependent report/finalization runs if applicable;
12. AgentResult created;
13. ResultDelivery remains PENDING under existing barrier;
14. execution timeline reconstructed;
15. restart/dedup verified;
16. tenant residue cleaned.

### Closure evidence

- P5 full regression;
- P6 focused coverage;
- Platform Full Gate;
- NSL v0.1 regression if NSL repo code changes;
- zero WRITE/WC imports/path audit.

---

## 11. Recommended Migration Sequence

Exact numbering follows current repository inventory.

Candidate responsibilities:

```text
2200  AE runtime worker/dispatcher operational support or indexes
2201  NSL step execution binding
2202  P6 StepResult READ extension / lineage
2203  optional timeline projection support
```

Do not create a timeline SoR table unless source audit proves necessary.

---

## 12. Rollout

Recommended flags/profiles:

```text
NEX_AE_AGENT_WORKER_MODE=disabled|enabled
NEX_AE_LOCAL_SKILL_MODE=disabled|shadow|required
NEX_AE_NSL_READ_BACKEND=v01|v02
```

Exact names may follow repository configuration standards.

### shadow

A shadow LOCAL_SKILL request must not perform duplicate live Tool execution merely for comparison.

Use contract validation/dry projection rather than duplicated side effects.

---

## 13. Rollback

Rollback target remains P5 behavior:

```text
LOCAL_SKILL disabled
→ existing P5 capabilities remain available
```

P6 migrations shall be additive/backward-readable.

---

## 14. Implementation Exit

P6 is implemented when one real IA READ executes through:

```text
P5 Plan
→ LOCAL_SKILL
→ AE Worker
→ verified NSP
→ canonical P6 request
→ NSL READ
→ StepResult
→ AgentResult
```

with stable IDs, complete timeline, worker restart safety, tenant fairness, and no WRITE.
