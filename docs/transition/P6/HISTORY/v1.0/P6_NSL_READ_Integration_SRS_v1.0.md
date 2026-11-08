# P6 — NSL READ Integration SRS v1.0

**Document Status:** PRE-IMPLEMENTATION BASELINE  
**Phase:** P6 — NSL READ Integration  
**Implementation Baseline:** NSL v0.1 As-Built  
**Target Contract:** Frozen NSL v0.2 READ-compatible subset  
**Predecessor:** P5 Agent Planning & Execution Foundation — IMPLEMENTATION COMPLETE  
**Frozen Authority:** `docs/frozen/v2.1/`

---

# 1. Purpose

P6 connects the P5 Agent Planning/Multi-Step Runtime to deterministic NSL READ execution.

P6 SHALL support:

```text
Natural-language Prompt
→ WorkIntent
→ AgentContext
→ AgentPlan
→ PlanValidation
→ Deterministic Compiler
→ ExecutablePlan
→ ExecutableStep(type=LOCAL_SKILL)
→ AE RuntimeJob
→ AE Runtime Worker
→ LOCAL_SKILL Executor
→ VerifiedSkillArtifact
→ SkillExecutionRequest
→ NSL READ
→ NSLResultSummary
→ StepResult
→ AgentResult
```

P6 SHALL NOT implement NSL WRITE.

---

# 2. Version Model

## P6-VER-001

The current executable NSL implementation baseline is NSL v0.1.

## P6-VER-002

The canonical P6 AE-facing integration contract SHALL target the Frozen NSL v0.2 READ-compatible subset.

## P6-VER-003

An adapter MAY execute the canonical P6 request through the current NSL v0.1 API.

## P6-VER-004

The backend may later switch to native NSL v0.2 READ without changing P5/P6 core identities or the AE-facing P6 contract.

## P6-VER-005

P6 documentation SHALL not claim NSL v0.2 runtime implementation exists until the NSL Track actually implements it.

---

# 3. Starting Point

P5 already provides:

- `AgentExecution`;
- `WorkIntent`;
- `AgentContext`;
- `AgentPlan`;
- deterministic `PlanValidation`;
- deterministic `ExecutablePlan`;
- S-key / E-key / UUID Step identity;
- durable `RuntimeJob` / Attempt;
- dependency-aware multi-step execution;
- `StepResult`;
- plan-level `AgentResult`;
- Prompt Registry;
- PENDING required `ResultDelivery`;
- restart/dedup PostgreSQL evidence.

P6 reuses these identities.

---

# 4. Pre-Architecture Decisions

P6 SHALL conform to the P6 Pre-Architecture Decision:

1. dedicated AE Runtime Worker;
2. tenant-aware dispatcher;
3. no blind Agent Runtime replay;
4. complete execution timeline;
5. AE-owned LOCAL_SKILL executor.

---

# 5. Explicit In Scope

- P6-CA01 v0.1 As-Built ↔ v0.2 READ contract closure;
- dedicated AE Runtime Worker process;
- tenant-aware bounded dispatcher;
- RuntimeJob operations base;
- capability-catalog extension for LOCAL_SKILL;
- exact skill ID/version binding;
- Skill Artifact Gateway;
- signed/verified NSP package admission;
- PackageTrustEvidence / VerifiedSkillArtifact projection;
- P6 NSL invocation identity persistence;
- `NSLExecutionId`;
- READ `BusinessOperationId`;
- canonical SkillExecutionRequest;
- v0.1 READ backend adapter;
- future v0.2 backend port;
- typed compiled-input projection;
- explicit resource refs;
- Principal/role/org/project/classification projection;
- NSL result mapper;
- StepResult extension for READ BusinessOperationId;
- complete AgentExecution timeline;
- P6 IA READ end-to-end closure.

---

# 6. Explicit Out of Scope

P6 MUST NOT implement:

- NSL WRITE;
- `approve`, WRITE suspension or approval resume;
- Agent FORMAL_APPROVAL;
- WC WorkItem;
- CA / PA / EA execution;
- `DELEGATE_WORK`;
- actual NSL WRITE IdempotencyKey;
- `operation_fingerprint`;
- CommitState;
- VerificationStatus;
- `UNKNOWN_COMMIT_STATE`;
- WRITE reconciliation;
- Enterprise OS WRITE;
- ResultDelivery publication/ACK;
- WA;
- Schedule.

---

# 7. Identity Model

P6 preserves:

```text
AgentExecutionId
ExecutablePlanId
LogicalPlanStepId      S*
CompiledStepKey        E*
ExecutableStepId       UUID
StepResultId
AgentResultId
```

P6 adds:

```text
NSLExecutionId
BusinessOperationId
SkillArtifactRef
PackageTrustEvidenceRef
```

Mandatory:

```text
AgentExecutionId != NSLExecutionId
ExecutableStepId != NSLExecutionId
BusinessOperationId != NSLExecutionId
BusinessOperationId != AgentExecutionId
```

One AgentExecution may have many NSLExecutionIds.

---

# 8. NSLExecutionId Requirements

## P6-ID-001

Each LOCAL_SKILL logical NSL execution SHALL receive one P6-owned/Integration-owned `NSLExecutionId`.

## P6-ID-002

The ID is allocated before backend invocation.

## P6-ID-003

It remains stable across:

- RuntimeJob technical retry;
- worker crash/reclaim;
- backend transport retry;
- any future NEW→WAIT→RESUME lifecycle for that same NSL execution.

## P6-ID-004

For the v0.1 backend adapter:

```text
P6 NSLExecutionId
→ NSL v0.1 SkillExecutionJob.execution_id
```

unless P6-CA01 finds a stronger compatibility requirement.

## P6-ID-005

A new semantic replan/new LOCAL_SKILL step receives a new NSLExecutionId.

---

# 9. BusinessOperationId Requirements

## P6-BOI-001

Frozen integration requires BusinessOperationId on every NSL invocation, including READ.

## P6-BOI-002

For P6 READ it is a stable semantic operation/correlation identity only.

It SHALL NOT imply WRITE authority.

## P6-BOI-003

BusinessOperationId SHALL be allocated and durably bound to the LOCAL_SKILL step before NSL invocation.

## P6-BOI-004

It remains stable across technical retry and restart.

## P6-BOI-005

The exact allocation mechanism SHALL be fixed by P6-CA01.

Recommended persistence authority is AE, either:

- columns bound to the P6 NSL step; or
- an AE-owned `NSLStepInvocationBinding` aggregate/table.

## P6-BOI-006

For P6 READ:

```text
operation_fingerprint = null
```

remains mandatory.

---

# 10. P5 StepResult Contract Transition

P5 v1.1 required BusinessOperationId null for all P5-produced results.

P6 SHALL introduce a controlled v1.2-or-P6 transition rule:

```text
non-NSL P5 step:
  business_operation_id = null

LOCAL_SKILL READ:
  business_operation_id = non-null stable value
  operation_fingerprint = null
```

This change SHALL be explicit in P6-CA01.

P6 SHALL not silently overwrite the historical P5 contract.

---

# 11. Capability Catalog Extension

## P6-CAP-001

P6 SHALL extend the capability snapshot with LOCAL_SKILL-capable descriptors.

## P6-CAP-002

Each NSL-backed capability SHALL bind:

- capability_id/version;
- `executable_step_type = LOCAL_SKILL`;
- `executor_kind = LOCAL_SKILL`;
- exact skill_id;
- exact skill_version;
- expected semantic identity/hash;
- input contract;
- output contract;
- operation semantics = READ;
- package/trust requirement;
- runtime contract reference.

## P6-CAP-003

No implicit `latest`.

## P6-CAP-004

Compiler SHALL fail closed if the exact skill artifact/executor contract is unavailable.

## P6-CAP-005

P6 SHALL not allow WRITE capability descriptors in an executable P6 READ plan.

---

# 12. Compiler Requirements

## P6-CMP-001

P5 deterministic compiler SHALL remain the only path from AgentPlan to ExecutableStep.

## P6-CMP-002

A LOCAL_CAPABILITY logically backed by NSL SHALL compile to:

```text
ExecutableStep.step_type = LOCAL_SKILL
executor_kind = LOCAL_SKILL
```

only after exact capability resolution.

## P6-CMP-003

Compiler SHALL bind exact skill/version and runtime contract refs.

## P6-CMP-004

Compiler SHALL NOT load/execute the NSP or invoke NSL.

## P6-CMP-005

Compiler SHALL NOT generate actual NSL WRITE IdempotencyKey.

## P6-CMP-006

Same semantic inputs/catalog snapshot SHALL retain deterministic ExecutablePlan hash regardless of NSLExecutionId/runtime UUID allocation.

NSLExecutionId and BusinessOperationId are runtime/integration identities, not deterministic compile hash inputs unless Frozen semantics explicitly require otherwise.

---

# 13. Skill Artifact Gateway

## P6-ART-001

P6 SHALL provide a single AE integration boundary for exact Skill artifact resolution.

## P6-ART-002

Input:

```text
tenant
skill_id
exact_skill_version
expected_semantic_hash
runtime_contract_ref
environment/trust policy
```

## P6-ART-003

The gateway SHALL not accept an implicit latest version.

## P6-ART-004

The gateway SHALL use the existing NSL package verification/trust capabilities rather than implementing independent cryptography in AE.

## P6-ART-005

Output SHALL be a canonical P6 `VerifiedSkillArtifact` projection containing at least:

```text
skill_ref
skill_id
exact_skill_version
semantic_hash
package_ref
package_hash
publisher/signing-key refs where applicable
trust_policy_ref
verified_at
backend_artifact_handle/ref
```

## P6-ART-006

Production P6 acceptance SHALL use signature-required package verification.

Development/test MAY use explicitly configured v0.1 development policy only in non-production tests.

## P6-ART-007

Package verification failure causes zero NSL runtime invocation.

---

# 14. SkillExecutionRequest

P6 canonical request follows the Frozen integration model.

Minimum fields:

```text
agent_execution_id
executable_plan_id
executable_step_id
nsl_execution_id
business_operation_id

tenant_id
skill_id
exact_skill_version
runtime_contract_ref

compiled_inputs
explicit_resource_refs

executing_principal
business_actor / on_behalf_of
effective_role_bindings
org_scope
project_scope
data_classification

correlation_id
causation_id

agent_context_ref
agent_context_hash

mode = NEW
resume_payload = null
```

P6 READ uses `mode=NEW`.

---

# 15. Context Projection

## P6-CTX-001

Whole AgentContext copy is forbidden.

## P6-CTX-002

Compiled inputs SHALL be derived from validated `compiled_input_bindings`.

## P6-CTX-003

Resource references SHALL be explicit and bounded.

## P6-CTX-004

Principal and authority metadata SHALL come from trusted/current sources, not LLM output.

## P6-CTX-005

Project scope may be null only if the selected READ Skill contract permits project-neutral execution.

## P6-CTX-006

Data classification SHALL be explicit.

## P6-CTX-007

The P6 v0.1 backend adapter may build v0.1 `StructuredRuntimeContext`, but it SHALL contain only the bounded projection necessary for v0.1 execution.

It SHALL NOT become a hidden full AgentContext copy.

---

# 16. v0.1 Backend Adapter

## P6-V01-001

P6 SHALL define an `NSLReadBackend` port or equivalent.

Initial implementation MAY be:

```text
V01ReadBackendAdapter
```

## P6-V01-002

Adapter maps:

```text
NSLExecutionId
→ SkillExecutionJob.execution_id

skill_id/version
→ exact v0.1 job selectors

compiled inputs
→ StructuredInputs

input provenance
→ InputProvenance

principal
→ VerifiedPrincipalContext

classification/retention
→ ExplicitDataHandlingPolicy

bounded runtime metadata
→ StructuredRuntimeContext
```

## P6-V01-003

The adapter SHALL use existing v0.1 `SkillExecutionWorker` or stable `nsl.api` surface, not private NSL internals.

## P6-V01-004

BusinessOperationId remains present in canonical P6 invocation/trace even if the v0.1 runtime does not consume it natively.

## P6-V01-005

No adapter logic may change NSL READ semantic status.

---

# 17. Future v0.2 Backend

P6 SHALL expose a backend boundary capable of later implementing:

```text
V02ReadBackendAdapter / NativeBackend
```

The v0.2 switch SHALL not require changes to:

- AgentExecutionId;
- ExecutablePlanId;
- ExecutableStepId;
- NSLExecutionId;
- BusinessOperationId;
- SkillExecutionRequest;
- StepResult identity.

---

# 18. Dedicated AE Runtime Worker

## P6-WRK-001

NSL execution SHALL occur outside the API request thread.

## P6-WRK-002

Worker lifecycle SHALL implement:

- readiness;
- heartbeat;
- bounded polling;
- graceful drain;
- SIGTERM;
- active claim accounting;
- lease-safe shutdown;
- restart recovery.

## P6-WRK-003

Worker SHALL use `ae_runtime_job`.

It SHALL NOT move Agent work into shared `service_jobs`.

## P6-WRK-004

Worker capability set SHALL be explicit.

P6 production worker must declare `LOCAL_SKILL` availability before claiming such steps.

---

# 19. Tenant Dispatcher

## P6-DSP-001

Dispatcher SHALL discover bounded runnable tenants.

## P6-DSP-002

Initial scheduling is deterministic bounded round-robin.

## P6-DSP-003

Per-tenant and global concurrency limits are mandatory.

## P6-DSP-004

One tenant cannot starve others in bounded tests.

## P6-DSP-005

Expired leases remain reclaimable.

## P6-DSP-006

High-cardinality execution/principal IDs are forbidden as generic metric labels.

---

# 20. RuntimeJob / Retry

## P6-JOB-001

Common Job replay and AE Runtime retry remain distinct.

## P6-JOB-002

LOCAL_SKILL technical retry reuses:

```text
AgentExecutionId
ExecutablePlanId
ExecutableStepId
NSLExecutionId
BusinessOperationId
```

## P6-JOB-003

Attempt history remains append-only.

## P6-JOB-004

Worker stale-completion protection remains mandatory.

## P6-JOB-005

P6 SHALL provide no arbitrary “replay same Agent step” API.

## P6-JOB-006

Dead-letter review does not itself execute the step.

---

# 21. NSL v0.1 READ Semantics

P6 SHALL preserve current v0.1 READ guarantees:

```text
exact registered tool
parameter validation
authorization
typed request
timeout
structured result
schema/type/classification validation
result hash verification
audit/provenance
```

P6 SHALL not bypass these checks in the adapter.

---

# 22. NSL Result Summary

P6 SHALL define a bounded `NSLResultSummary` projection.

It SHOULD include:

```text
schema_version
nsl_execution_id
business_operation_id
skill_id
skill_version
skill_semantic_hash
package/trust refs

runtime_status

output_refs / output_hashes
artifact_refs
evidence_refs

validation summary
resource usage summary

error_code/ref if applicable
result_hash
```

It SHALL NOT copy the raw NSL audit journal.

---

# 23. Result Mapping

Minimum P6 mapping:

| NSL runtime status | P6 Step outcome |
|---|---|
| `COMPLETED` | `SUCCEEDED` |
| `CANCELLED` | `CANCELLED` |
| `VALIDATION_ERROR` | `FAILED` or contract-defined `BLOCKED`; P6-CA01 fixes exact mapping |
| `TOOL_ERROR` | `FAILED` |
| `LIMIT_EXCEEDED` | `FAILED` |
| generic runtime failure | `FAILED` |

No failure is converted into successful empty output.

P6-CA01 SHALL freeze the complete mapping against current v0.1 `ExecutionStatus`.

---

# 24. StepResult Requirements

## P6-SR-001

P6 LOCAL_SKILL StepResult SHALL preserve:

```text
AgentExecutionId
ExecutablePlanId
ExecutableStepId
CompiledStepKey
LogicalPlanStepId
NSLExecutionId reference/evidence
BusinessOperationId
```

## P6-SR-002

For LOCAL_SKILL READ:

```text
business_operation_id != null
operation_fingerprint = null
```

## P6-SR-003

Detailed NSL audit remains referenced, not copied.

## P6-SR-004

Same terminal semantic NSL result replay SHALL remain idempotent.

---

# 25. Timeline / Observability

P6 SHALL provide complete execution timeline visibility.

At minimum, one LOCAL_SKILL step timeline includes:

```text
RuntimeJob queued
RuntimeJob claimed
RuntimeAttempt started
ExecutableStep running
VerifiedSkillArtifact admitted
NSL execution started
NSL result terminal
StepResult persisted
RuntimeJob done
next step/finalization
```

The timeline SHALL use canonical DB records/projections.

---

# 26. Security Requirements

## P6-SEC-001

Only verified package artifacts may reach NSL production execution.

## P6-SEC-002

No package version substitution.

## P6-SEC-003

No raw credentials in SkillExecutionRequest.

## P6-SEC-004

User/LLM cannot authoritatively set TenantId, Principal, RoleBinding, Project scope, data classification or trust result.

## P6-SEC-005

NSL package/trust failure is fail-closed.

## P6-SEC-006

AE SHALL not independently reinterpret cryptographic signature validity.

---

# 27. Process Isolation

Current NSL v0.1 includes runtime process-isolation support.

P6 SHALL decide in P6-CA01 / implementation plan whether production P6 worker:

- directly hosts the framework-neutral NSL worker in-process; or
- invokes the NSL runtime through an isolation adapter.

The selected profile SHALL preserve AE worker survival on NSL runtime crash/timeout.

A production-read acceptance test SHOULD include crash/timeout isolation.

---

# 28. Storage / Persistence

Recommended P6 AE-local persistence:

```text
ae_nsl_step_execution
or equivalent
```

Minimum logical fields:

```text
tenant_id
nsl_execution_id
agent_execution_id
executable_plan_id
executable_step_id
business_operation_id

skill_id
skill_version
skill_semantic_hash
verified_artifact_ref
package_trust_ref

request_hash
backend_profile
state
result_summary_ref/hash
created_at
updated_at
```

Unique binding:

```text
(tenant_id, executable_step_id)
```

unless Frozen/CA01 requires multiple NSL executions per step.

No cross-service FK to NSL storage.

---

# 29. P6-CA01 Mandatory Closure

Before P6-S2+ implementation, Codex SHALL close:

1. exact v0.1 `SkillExecutionJob` / Worker/API mapping;
2. exact v0.2 READ `SkillExecutionRequest` transition schema;
3. exact BusinessOperationId allocation/persistence;
4. exact NSLExecutionId allocation/stability;
5. P5 StepResult contract controlled amendment;
6. v0.1/v0.2 result status mapping;
7. exact `VerifiedSkillArtifact` machine shape;
8. production trust policy;
9. context projection schema;
10. backend crash/isolation profile;
11. selected Golden READ Skill/Tool fixture;
12. P6 timeline projection shape.

---

# 30. Required Tests

## Worker
- startup/readiness;
- heartbeat;
- drain;
- shutdown;
- restart;
- stale lease rejection.

## Dispatcher
- 2+ tenant fairness;
- per-tenant concurrency;
- global concurrency;
- noisy-tenant isolation.

## Artifact
- exact version;
- package tamper;
- signer/key mismatch;
- semantic hash mismatch;
- unsigned production reject.

## Identity
- AgentExecutionId != NSLExecutionId;
- stable NSLExecutionId retry;
- stable BusinessOperationId retry;
- new step → new identities.

## Context
- typed compiled inputs;
- full AgentContext copy negative;
- untrusted authority injection negative.

## Backend
- v0.1 job round trip;
- READ completed;
- tool failure;
- validation failure;
- timeout/crash isolation;
- no semantic status rewriting.

## Result
- NSLResultSummary;
- StepResult BusinessOperationId non-null;
- operation_fingerprint null;
- audit refs only;
- idempotent restart.

## Replay
- no arbitrary runtime replay;
- dead-letter review no execution.

## E2E
- prompt → LOCAL_SKILL → verified NSP → NSL READ → StepResult → AgentResult.

---

# 31. Quality Gates

Maintain repository standards:

```text
statement coverage >= 95%
branch coverage    >= 94% for Platform repository
```

NSL repository changes, if performed in parallel, SHALL maintain its own v0.1/v0.2 quality gates.

P6 SHALL include:

- unit/regression;
- PostgreSQL protected smoke;
- worker process lifecycle tests;
- contract/schema tests;
- existing P5 regression;
- Playwright user journey when user-visible behavior changes.

---

# 32. P6 Acceptance Scenario — IA READ

A representative P6 Golden READ scenario SHALL prove:

```text
User Prompt
→ WorkIntent
→ AgentContext
→ AgentPlan
→ LOCAL_SKILL plan step
→ VALID
→ ExecutablePlan
→ RuntimeJob
→ Worker
→ exact VerifiedSkillArtifact
→ SkillExecutionRequest
→ NSL v0.1 backend or v0.2 READ backend
→ actual NSL READ semantics
→ NSLResultSummary
→ StepResult
→ deterministic report/finalization
→ AgentResult
```

No WRITE and no WC.

---

# 33. P6 Exit Gate

P6 closes only when:

- P6-CA01 is closed;
- production-like AE Runtime Worker exists;
- tenant dispatcher is bounded/fair;
- LOCAL_SKILL is a real registered executor;
- exact signed/verified NSP artifact admission works;
- NSL v0.1 READ backend executes through the canonical P6 request boundary, or native v0.2 READ is available;
- NSLExecutionId and BusinessOperationId are traceable/stable;
- StepResult maps correctly;
- complete timeline is available;
- E2E-01 IA READ passes;
- no NSL WRITE/WC scope leaked in;
- P5 regression remains PASS.
