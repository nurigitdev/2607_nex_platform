# P6 Architecture Decisions v1.0

**Status:** PRE-IMPLEMENTATION DESIGN BASELINE  
**Phase:** P6 — NSL READ Integration

---

## P6-DEC-01 — Version-neutral P6 integration name

P6 is named **NSL READ Integration**.

Implementation backend version and target integration contract version are separate concerns.

```text
backend now   = NSL v0.1
target contract = Frozen NSL v0.2 READ subset
```

---

## P6-DEC-02 — AE-facing P6 contract targets v0.2 semantics

P6 SHALL not expose the v0.1 `SkillExecutionJob` as the long-term AE domain contract.

Canonical AE-facing request is the Frozen `SkillExecutionRequest` model.

A v0.1 adapter MAY translate it into current `SkillExecutionJob` / `ExecutionRequest`.

---

## P6-DEC-03 — AgentExecutionId and NSLExecutionId never collapse

```text
AgentExecutionId != NSLExecutionId
```

One AgentExecution may invoke multiple NSL executions.

For one logical NSL step execution, `NSLExecutionId` remains stable across technical retry and any future NEW→WAIT→RESUME lifecycle.

---

## P6-DEC-04 — BusinessOperationId exists for READ too

Frozen integration requires `BusinessOperationId` on every NSL invocation.

For READ it is:

> stable Agent/Platform-owned semantic operation/correlation identity.

It is not a WRITE authorization and does not imply side effects.

For one LOCAL_SKILL READ step:

```text
BusinessOperationId
= stable across technical retry/restart
```

P6-CA01 SHALL define allocation and persistence.

---

## P6-DEC-05 — P5 StepResult WRITE-field rule requires P6 refinement

P5 correctly enforced:

```text
business_operation_id = null
operation_fingerprint = null
```

because P5 had no NSL invocation.

Frozen P6 READ requires BusinessOperationId.

Therefore P6 SHALL make a controlled transition-contract change:

```text
P5/non-NSL step:
  business_operation_id = null

P6 LOCAL_SKILL READ step:
  business_operation_id = stable non-null

P6 READ:
  operation_fingerprint = null
```

`operation_fingerprint` remains WRITE-specific.

P6 SHALL not silently reinterpret the P5 v1.1 contract.

---

## P6-DEC-06 — Dedicated AE Runtime Worker precedes production NSL calls

NSL invocation occurs from the dedicated AE Runtime Worker / StepExecutionEngine boundary, never directly from the API request thread.

---

## P6-DEC-07 — Shared JobQueue remains separate

```text
service_jobs != ae_runtime_job
```

Shared worker lifecycle primitives may be reused.

Agent RuntimeJob domain/replay/lease authority remains AE-owned.

---

## P6-DEC-08 — Tenant dispatch is bounded and deterministic

Initial P6 policy:

```text
runnable tenant discovery
→ deterministic bounded round-robin
→ per-tenant concurrency
→ global concurrency
```

No user-controlled runtime priority.

---

## P6-DEC-09 — No blind Agent Runtime replay

Agent Runtime continuation requires explicit semantics:

- technical retry;
- wait/resume;
- reconciliation;
- replan;
- publication retry.

Operator-created arbitrary “run again” RuntimeJobs are prohibited.

---

## P6-DEC-10 — LOCAL_SKILL executor is AE-owned

NSL owns deterministic Skill execution.

AE owns the executor that adapts:

```text
ExecutableStep
→ VerifiedSkillArtifact
→ SkillExecutionRequest
→ NSL
→ StepResult
```

---

## P6-DEC-11 — Exact package/version only

No implicit latest.

```text
skill_id
+ exact_skill_version
+ semantic/package identity
→ exact verified artifact
```

P6 runtime cannot silently substitute a newer Skill.

---

## P6-DEC-12 — Verified NSP package boundary is reused

Current NSL v0.1 already verifies signed NSP and exposes verified package resolution.

P6 SHALL reuse those trust capabilities.

P6 SHALL not implement a second independent signature verifier in AE.

AE/Skill Artifact Gateway projects package trust into canonical `VerifiedSkillArtifact` evidence.

---

## P6-DEC-13 — AgentContext is projected, never copied

Forbidden:

```text
AgentContext JSON → NSL runtime_context
```

Required:

```text
AgentContext
→ deterministic typed binding/projection
→ compiled_inputs
+ explicit_resource_refs
+ bounded identity/scope/provenance
```

---

## P6-DEC-14 — v0.1 backend adapter is temporary but first-class

The initial backend MAY use current:

```text
nsl.api.SkillExecutionJob
nsl.api.SkillExecutionWorker
RuntimeResultEnvelope
```

The adapter SHALL:

- preserve exact skill/version;
- map P6 `NSLExecutionId` to v0.1 runtime `execution_id`;
- map typed inputs/provenance;
- map principal/data policy;
- supply only bounded runtime context;
- preserve audit/snapshot evidence refs;
- convert v0.1 result into P6 `NSLResultSummary`.

When v0.2 runtime is ready, this backend adapter may be replaced without changing AE P6 identities.

---

## P6-DEC-15 — READ result mapping is conservative

Only actual NSL runtime completion maps to a successful StepResult.

Examples:

```text
COMPLETED
→ StepResult.SUCCEEDED

VALIDATION_ERROR / TOOL_ERROR / LIMIT_EXCEEDED / FAILED
→ StepResult.FAILED or BLOCKED according to fixed mapper

CANCELLED
→ StepResult.CANCELLED
```

No tool error is converted to an empty successful result.

---

## P6-DEC-16 — NSL raw audit is not copied into AE

NSL remains detailed execution evidence SoR.

AE stores:

- stable evidence ref;
- hash;
- classification;
- minimal semantic summary.

---

## P6-DEC-17 — Worker timeline becomes complete execution projection

P6 timeline includes planning, RuntimeJob/Attempt, LOCAL_SKILL, NSL execution and result lineage.

It is a read projection, not a second state SoR.

---

## P6-DEC-18 — v0.2 WRITE remains entirely out of P6

P6 SHALL not implement:

- NSL WRITE;
- approval;
- checkpoint/resume approval;
- actual WRITE idempotency key;
- commit state;
- verification status;
- UNKNOWN_COMMIT_STATE.

READ compatibility work must not preemptively add partial WRITE behavior.
