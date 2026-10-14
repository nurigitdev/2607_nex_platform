# P6 — NSL READ Integration SRS v1.1

**Document Status:** P6-CA01 SOURCE-BACKED CONTRACT BASELINE; IMPLEMENTATION PENDING
**Supersedes:** v1.0
**Implementation Baseline:** NSL v0.1 As-Built
**Target Contract:** Frozen NSL v0.2 READ-compatible subset

# 1. Purpose

P6 connects the completed P5 Agent Planning/Multi-Step Runtime to deterministic NSL READ execution.

```text
Prompt
→ WorkIntent
→ AgentContext
→ AgentPlan
→ PlanValidation
→ ExecutablePlan
→ ExecutableStep(LOCAL_SKILL)
→ AE RuntimeJob
→ capability-aware AE Worker
→ VerifiedSkillArtifact
→ durable NSLStepExecutionBinding
→ SkillExecutionRequest
→ NSL READ Backend
→ NSLResultSummary
→ StepResult v1.2
→ AgentResult
```

P6 SHALL NOT implement NSL WRITE.

# 2. Entry Gate

P6-CA01 is closed by
`P6_CA01_Source_Backed_READ_Contract_Closure_v1.0.md`. P6-S0 is the next
authorized implementation Slice.

```text
CA01A
→ source-backed CA01
→ S0
→ S1
→ S2
→ S3
→ S4
→ S5
→ S6
→ S7
```

P6-CA01 must inspect the exact NSL checkout in the Codex workspace and record its SHA.

# 3. In Scope

- dedicated AE Runtime Worker;
- homogeneous initial worker capability profile;
- capability-aware atomic RuntimeJob claim;
- one active DB-protected dispatcher leader;
- tenant fairness/backpressure;
- exact LOCAL_SKILL capability binding;
- Skill Artifact Gateway;
- verified NSP/package/trust projection;
- NSLExecutionId;
- READ BusinessOperationId;
- durable NSLStepExecutionBinding;
- SkillExecutionRequest;
- v0.1 READ backend adapter;
- future v0.2 READ backend port;
- typed input/context projection;
- NSLResultSummary;
- StepResult semantic schema 1.2;
- deterministic complete-retained-evidence timeline;
- E2E-01 IA READ.

# 4. Out of Scope

- WC / DELEGATE_WORK;
- CA/PA/EA admission;
- NSL WRITE;
- approval;
- WRITE checkpoint/resume;
- WRITE IdempotencyKey;
- CommitState;
- VerificationStatus;
- UNKNOWN_COMMIT_STATE reconciliation;
- Enterprise OS WRITE;
- ResultDelivery ACK/publication;
- WA;
- Schedule;
- heterogeneous worker routing/autoscaling control plane.

# 5. Version Model

## P6-VER-001
Current executable runtime baseline is NSL v0.1.

## P6-VER-002
AE-facing P6 contract targets Frozen NSL v0.2 READ semantics.

## P6-VER-003
Initial backend MAY adapt the canonical request to current v0.1 `nsl.api`.

## P6-VER-004
A native v0.2 backend may replace the adapter without changing AE identities or P6 request/result contracts.

# 6. Identity Contract

Distinct identities:

```text
AgentExecutionId
ExecutablePlanId
ExecutableStepId
NSLExecutionId
BusinessOperationId
StepResultId
AgentResultId
```

Mandatory:

```text
AgentExecutionId != NSLExecutionId
ExecutableStepId != NSLExecutionId
BusinessOperationId != NSLExecutionId
BusinessOperationId != AgentExecutionId
```

# 7. NSLExecutionId Allocation

## P6-ID-001
AE Integration allocates NSLExecutionId before backend invocation.

## P6-ID-002
AE durably binds the ID to the LOCAL_SKILL ExecutableStep before the first external/backend call.

## P6-ID-003
Technical retry, lease reclaim and worker restart reuse the same ID.

## P6-ID-004
NSL Runtime validates/consumes the supplied ID and owns lifecycle semantics associated with it.

## P6-ID-005
Initial v0.1 mapping:

```text
NSLExecutionId
→ SkillExecutionJob.execution_id
```

## P6-ID-006
Semantic replan/new ExecutableStep creates a new NSLExecutionId.

# 8. BusinessOperationId

## P6-BOI-001
Every NSL invocation, including READ, carries BusinessOperationId.

## P6-BOI-002
For P6 READ it is a stable Agent/Platform semantic operation/correlation identity only.

## P6-BOI-003
AE allocates/persists it in the same pre-invocation binding transaction as NSLExecutionId.

## P6-BOI-004
Retry/restart reuse it.

## P6-BOI-005
For P6 READ:

```text
operation_fingerprint = null
```

# 9. NSLStepExecutionBinding

P6 SHALL create/load one durable AE-owned binding per LOCAL_SKILL ExecutableStep.

```text
UNIQUE (tenant_id, executable_step_id)
```

Minimum logical fields:

```text
tenant_id
agent_execution_id
executable_plan_id
executable_step_id
nsl_execution_id
business_operation_id
skill_id
exact_skill_version
skill_semantic_hash
verified_artifact_ref
verified_artifact_hash
package_trust_ref
request_hash
backend_profile
state
result_summary_ref
result_summary_hash
created_at
updated_at
```

The allocation transaction commits before backend execution.

P6 supports one logical NSL execution per ExecutableStep. Future multi-invocation-per-step semantics require a versioned change.

# 10. StepResult v1.2

Historical P5 schema 1.1 remains readable/immutable.

P6 writer emits schema 1.2.

Rules:

```text
non-NSL:
  business_operation_id = null
  operation_fingerprint = null

LOCAL_SKILL READ:
  business_operation_id = required non-null
  operation_fingerprint = null
```

Condition is based on canonical executor/invocation kind, not caller-provided values.

# 11. Capability Catalog

P6 adds LOCAL_SKILL-capable descriptors with exact:

- capability ID/version;
- executable step type;
- executor kind;
- skill ID/version;
- semantic hash;
- input/output contracts;
- runtime contract ref;
- operation semantics = READ;
- package/trust requirements.

No implicit latest.

P6 compiler rejects unavailable exact skill/executor contracts.

# 12. Compiler

P5 deterministic compiler remains the only path from AgentPlan to ExecutableStep.

A valid NSL-backed capability compiles to:

```text
step_type = LOCAL_SKILL
executor_kind = LOCAL_SKILL
```

Compiler binds exact skill/version/runtime contract but does not verify package bytes or execute NSL.

Runtime identities NSLExecutionId/BusinessOperationId do not become deterministic plan-hash inputs.

# 13. Skill Artifact Gateway

Input:

```text
tenant
skill_id
exact_skill_version
expected_semantic_hash
runtime_contract_ref
environment/trust policy
```

Output: canonical `VerifiedSkillArtifact` projection.

It must bind:

- exact skill/version;
- semantic hash;
- package ID/hash;
- publisher/signing-key evidence;
- trust-policy ref;
- verified_at;
- backend artifact handle/ref.

AE SHALL not implement duplicate crypto.

Production acceptance requires signature-required package verification.

Package/trust failure causes zero NSL runtime calls.

# 14. SkillExecutionRequest

Canonical P6 request includes:

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

P6-CA01 freezes exact machine shape.

# 15. Context Projection

Whole AgentContext copy is forbidden.

Compiled inputs derive only from validated bindings.

Resource refs are explicit/bounded.

Principal/role/project/classification come from trusted authority sources, not LLM output.

Project scope may be null only if the selected READ Skill permits project-neutral execution.

# 16. v0.1 Backend Adapter

Define stable backend port:

```text
NSLReadBackend
```

Initial implementation:

```text
V01ReadBackendAdapter
```

Maps:

```text
NSLExecutionId          → SkillExecutionJob.execution_id
skill ID/version/hash   → exact v0.1 selectors
compiled inputs         → StructuredInputs
provenance              → InputProvenance
principal               → VerifiedPrincipalContext
classification/policy   → ExplicitDataHandlingPolicy
bounded metadata        → StructuredRuntimeContext
```

Fields not consumed by v0.1 remain preserved in AE binding/timeline.

Use stable `nsl.api`, not broad private internals.

# 17. Worker Process

AE Runtime Worker SHALL provide:

- configuration validation;
- readiness;
- heartbeat;
- bounded polling;
- graceful drain;
- signal handling;
- active claim accounting;
- lease-safe shutdown;
- restart recovery;
- bounded concurrency; and
- privacy-safe logging with no raw prompt, response, document, credential, or
  runtime payload content.

Worker declares supported executor kinds at startup.

Configured executor without implementation → startup fail.

# 18. Capability-Aware Atomic Claim

Claim transaction SHALL check:

```text
RuntimeJob runnable
AND referenced ExecutableStep exists
AND ExecutableStep.executor_kind supported by worker
AND lease CAS succeeds
```

in one database transaction.

Unsupported/malformed jobs are not normally executable and remain observable for explicit handling.

# 19. Dispatcher Leadership / Fairness

One active dispatcher leader per AE Runtime queue.

Leadership protected by DB lease/advisory lock/equivalent.

Dispatch round:

1. bounded runnable tenants;
2. sort by oldest runnable work + tenant_id;
3. visit each at most once;
4. apply per-tenant claim cap;
5. stop at global capacity;
6. rebuild next round from DB.

Acceptance proves continuously busy tenant cannot starve another runnable tenant.

User-controlled runtime priority is not permitted in P6.

# 20. Backpressure

P6 bounds:

- global active claims;
- per-tenant active claims;
- batch size;
- worker concurrency;
- runnable depth;
- delayed/dead-letter retention.

P6-S1 fixes exact admission reject-or-delay behavior/error codes.

No high-cardinality IDs as general metric labels.

## Minimum operational metrics

P6 exposes bounded-cardinality operational metrics for at least:

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
throughput/failure by bounded executor/job type
```

## AG read-only operations boundary

NeX-AG MAY consume protected AE operational APIs and projections.

NeX-AG SHALL NOT claim AE RuntimeJobs, own dispatcher leadership, or mutate AE
RuntimeJob, RuntimeAttempt, ExecutableStep, or NSLStepExecutionBinding records.

# 21. Runtime Retry / Replay

```text
Common Job replay != Agent Runtime replay
```

Technical retry preserves:

```text
AgentExecutionId
ExecutablePlanId
ExecutableStepId
NSLExecutionId
BusinessOperationId
```

Attempt history is append-only.

Stale lease completion is rejected.

No generic replay API exists.

Dead-letter review does not execute the step.

# 22. v0.1 READ Semantics

Adapter SHALL preserve:

```text
exact registered Tool
parameter validation
authorization
typed request
timeout
structured result
schema/type/classification validation
result hash validation
audit/provenance
```

No failure-to-empty-success conversion.

# 23. NSLResultSummary

P6 defines bounded summary with at least:

```text
schema_version
nsl_execution_id
business_operation_id
skill_id/version/semantic_hash
artifact/package/trust refs
runtime_status
output refs/hashes
artifact/evidence refs
validation summary
resource summary
error code/ref
result_hash
```

Raw NSL audit journal is not copied.

# 24. Result Mapping

P6-CA01 must exhaustively map actual v0.1 `ExecutionStatus`.

No generic fallback is accepted without review.

Baseline intent:

```text
COMPLETED       → SUCCEEDED
CANCELLED       → CANCELLED
TOOL_ERROR      → FAILED
LIMIT_EXCEEDED  → FAILED
VALIDATION_ERROR→ CA01-fixed FAILED or BLOCKED
other explicit status → CA01-fixed mapping
```

# 25. Timeline

Timeline is reconstructed from canonical persisted records/evidence.

Ordering:

```text
(event_time, phase_order, source_type_order, stable_source_id)
```

Then assign one-based sequence.

Version `phase_order` and `source_type_order`.

Do not infer unavailable state transitions.

Projection gaps are explicit metadata.

No independent timeline SoR unless S6 source audit proves a required transition cannot be represented.

# 26. Process Isolation

P6-CA01 selects:

- in-process v0.1 Worker backend; or
- process-isolated backend profile.

Whichever is selected must prove AE worker survival on NSL crash/timeout.

# 27. Security

- production execution uses verified package artifacts;
- exact version only;
- no raw credentials in request;
- user/LLM cannot authoritatively set tenant/principal/roles/project/classification/trust;
- trust failure fail-closed;
- AE does not reinterpret signature cryptography.

# 28. Required P6-CA01 Closure

Before any Slice:

1. exact NSL checkout SHA;
2. exact v0.1 API mapping;
3. SkillExecutionRequest schema;
4. NSLExecutionId allocation/persistence;
5. BusinessOperationId allocation/persistence;
6. StepResult v1.2 schema;
7. VerifiedSkillArtifact schema;
8. NSLResultSummary schema;
9. NSLStepExecutionBinding schema;
10. exhaustive status mapper;
11. context projection schema;
12. process profile;
13. Golden READ fixture;
14. source-to-contract matrix;
15. negative-test matrix.

# 29. Tests

Worker:
- startup/readiness/heartbeat/drain/shutdown/restart.

Claim:
- supported capability only;
- atomic eligibility + lease CAS;
- stale lease rejection.

Dispatcher:
- leader exclusivity;
- fairness;
- per/global caps;
- noisy tenant;
- restart reconstruction.

Artifact:
- exact version;
- tamper;
- signer/key mismatch;
- unsigned production;
- semantic mismatch.

Identity:
- non-collapse;
- stable retry/restart IDs;
- new step → new IDs.

Context:
- typed projection;
- full AgentContext negative;
- untrusted authority injection negative.

Backend:
- v0.1 round trip;
- completion/failure/cancel/limit;
- crash/timeout containment;
- no semantic rewriting.

Result:
- NSLResultSummary;
- StepResult v1.2;
- BOI non-null for LOCAL_SKILL READ;
- operation_fingerprint null;
- idempotent restart.

Timeline:
- deterministic same-snapshot output;
- tie handling;
- no invented state.

E2E:
- Prompt → LOCAL_SKILL → verified NSP → NSL READ → StepResult → AgentResult.

# 30. Quality

Platform:
```text
statement >= 95%
branch >= 94%
```

Preserve P5 Full Gate and user-visible regression.

If NSL repo changes, maintain its own quality baseline/gates.

# 31. Exit Gate

P6 closes when one real IA READ proves:

```text
Agent Plan
→ LOCAL_SKILL
→ AE RuntimeJob
→ capability-aware Worker
→ exact VerifiedSkillArtifact
→ durable NSLStepExecutionBinding
→ canonical SkillExecutionRequest
→ NSL READ
→ NSLResultSummary
→ StepResult v1.2
→ AgentResult
```

with stable IDs, dispatcher fairness, worker restart safety, deterministic timeline, no WRITE/WC scope leakage and P5 regression PASS.
