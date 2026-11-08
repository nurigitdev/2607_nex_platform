# P6 Transition Implementation Baseline

**Status:** PRE-IMPLEMENTATION DOCUMENT SET  
**Phase:** P6 — NSL READ Integration  
**Implementation Baseline:** NSL v0.1 As-Built (`nurigitdev/2608_nsl`, commit `803f22aadc39...`)  
**Target Contract:** Frozen NSL v0.2 READ-compatible integration subset  
**Predecessor:** P5 Agent Planning & Execution Foundation — IMPLEMENTATION COMPLETE  
**Target location:** `docs/transition/P6/`

---

## 1. Naming Decision

The primary SRS filename is:

```text
P6_NSL_READ_Integration_SRS_v1.0.md
```

rather than:

```text
P6_NSL_v0.1_READ_Integration_SRS_v1.0.md
P6_NSL_v0.2_READ_Integration_SRS_v1.0.md
```

Reason:

```text
Current executable runtime = NSL v0.1
Frozen product target      = NSL v0.2
P6 capability scope        = READ integration
```

P6 SHALL define an AE-facing contract compatible with the Frozen v0.2 integration model while allowing the first runtime backend to be the current v0.1 implementation through an explicit adapter.

A future switch from the v0.1 backend to a v0.2 READ backend SHALL NOT require renaming P6 identities or changing the AE planning/runtime contract.

---

## 2. P6 Target Shape

```text
AgentPlan
→ Plan Validator
→ Deterministic Compiler
→ ExecutableStep(type=LOCAL_SKILL)
→ AE RuntimeJob
→ AE Runtime Worker
→ LOCAL_SKILL Executor
→ Skill Artifact Gateway
→ VerifiedSkillArtifact
→ SkillExecutionRequest
→ NSL READ Backend
→ NSLResultSummary
→ StepResult
→ AgentResult
```

---

## 3. Version Boundary

### NSL v0.1 provides today

- READ execution semantics;
- exact Tool Contract validation;
- CHECK/EMIT;
- principal/data-policy boundary;
- audit/snapshot/replay;
- NSP package build/verification/signature;
- exact skill ID/version resolution from verified NSP;
- framework-neutral `SkillExecutionWorker`;
- `SkillExecutionJob` / `RuntimeResultEnvelope`;
- process isolation and high coverage.

### Frozen NSL v0.2 adds/changes contract surface

- `SkillExecutionRequest` identity model;
- explicit `AgentExecutionId != NSLExecutionId`;
- `BusinessOperationId` on every invocation, including READ;
- explicit Agent/Plan/Step IDs;
- deterministic context projection;
- `PackageTrustEvidence` / `VerifiedSkillArtifact`;
- additive v0.2 Runtime result fields;
- future Approval/WRITE/Commit/Verification semantics.

P6 implements only the READ-compatible subset.

---

## 4. Required Read Order

1. `P6_Pre_Architecture_Decision_Agent_Runtime_Worker_Dispatch_Replay_Timeline_LOCAL_SKILL_v1.0.md`
2. `README.md`
3. `P6_Architecture_Decisions_v1.0.md`
4. `P6_NSL_v0.1_to_v0.2_READ_Compatibility_Matrix_v1.0.md`
5. `P6_NSL_READ_Integration_SRS_v1.0.md`
6. `P6_Scope_Review_v1.0.md`
7. `P6_Issue_Register_v1.0.md`
8. `P6_Agent_NSL_READ_Integration_Traceability_v1.0.md`
9. `P6_CA01_v0.1_AsBuilt_to_v0.2_READ_Contract_Closure_Plan_v1.0.md`
10. `P6_Source_Audit_and_Implementation_Plan_v1.0.md`

Frozen authority remains above all transition documents.

---

## 5. Pre-Implementation Gate

Before NSL integration feature code begins, P6-CA01 SHALL close:

- exact v0.1 API mapping;
- exact v0.2 READ request/result subset;
- `NSLExecutionId` allocation/stability;
- READ `BusinessOperationId` allocation/stability;
- Verified NSP / `VerifiedSkillArtifact` mapping;
- typed compiled-input/context projection;
- result mapping;
- P5 StepResult amendment needed for READ BusinessOperationId traceability.

P6-S0/S1 worker/dispatcher foundations MAY be implemented only after this document set is accepted; P6-S2+ SHALL not begin before P6-CA01 closes.

---

## 6. P6 Exit Shape

```text
PROMPT
→ AgentExecution
→ WorkIntent
→ AgentContext
→ AgentPlan
→ VALID
→ ExecutablePlan
→ LOCAL_SKILL ExecutableStep
→ AE RuntimeJob
→ AE Worker
→ VerifiedSkillArtifact
→ SkillExecutionRequest
→ NSL READ
→ NSLResultSummary
→ StepResult
→ AgentResult
```

with:

- no NSL WRITE;
- no WC;
- no blind RuntimeJob replay;
- exact execution timeline;
- real PostgreSQL worker/restart evidence;
- P5 regression PASS.
