# P6 Transition Implementation Baseline v1.1

**Status:** P6-CA01A CONSOLIDATED PRE-IMPLEMENTATION BASELINE
**Phase:** P6 — NSL READ Integration
**Implementation Baseline:** NSL v0.1 As-Built
**Target Contract:** Frozen NSL v0.2 READ-compatible integration subset
**Predecessor:** P5 Agent Planning & Execution Foundation — IMPLEMENTATION COMPLETE

## 1. Naming

Stable SRS name:

```text
P6_NSL_READ_Integration_SRS_v1.1.md
```

```text
Current executable backend = NSL v0.1
AE-facing target contract  = Frozen NSL v0.2 READ-compatible subset
```

## 2. Canonical Entry Sequence

CA01A supersedes the v1.0 partial-parallel rule.

```text
P6 document-set review
→ P6-CA01A design consistency closure
→ P6-CA01 source-backed contract closure
→ P6-S0 AE Runtime Worker Foundation
→ P6-S1 Tenant Dispatcher / Operations
→ P6-S2 Skill Artifact Gateway
→ P6-S3 Request / Identity Binding
→ P6-S4 LOCAL_SKILL Executor
→ P6-S5 NSL READ Backend Integration
→ P6-S6 Result / Timeline Integration
→ P6-S7 E2E-01 IA READ Closure
```

**No P6 feature Slice begins before P6-CA01 closes.**

## 3. Authority

```text
Frozen Platform v2.1 / Agent v2.1 / NSL v0.2
> approved source-backed P6-CA01 outputs
> P6-CA01A Pre-Implementation Design Consistency Closure v1.0
> this P6 v1.1 consolidated transition set
> P6 v1.0 historical transition docs
> P4/P5 historical transition docs
> implementation convenience
```

## 4. Required Reading Order

1. Frozen baseline and Agent↔NSL Integration Contract
2. `P6_CA01A_Pre_Implementation_Design_Consistency_Closure_v1.0.md`
3. `P6_Pre_Architecture_Decision_Agent_Runtime_Worker_Dispatch_Replay_Timeline_LOCAL_SKILL_v1.1.md`
4. `P6_Architecture_Decisions_v1.1.md`
5. `P6_NSL_v0.1_to_v0.2_READ_Compatibility_Matrix_v1.1.md`
6. `P6_NSL_READ_Integration_SRS_v1.1.md`
7. `P6_Scope_Review_v1.1.md`
8. `P6_Issue_Register_v1.1.md`
9. `P6_Agent_NSL_READ_Integration_Traceability_v1.1.md`
10. `P6_CA01_v0.1_AsBuilt_to_v0.2_READ_Contract_Closure_Plan_v1.1.md`
11. `P6_Source_Baseline_Record_v1.1.md`
12. current Platform P5 As-Built and exact NSL v0.1 source checkout
13. `P6_Source_Audit_and_Implementation_Plan_v1.1.md`

## 5. CA01A Non-Negotiable Rules

```text
AE allocates/persists:
  NSLExecutionId
  BusinessOperationId

NSL Runtime owns:
  lifecycle semantics for supplied NSLExecutionId
```

```text
one LOCAL_SKILL step
→ one durable NSLStepExecutionBinding
→ UNIQUE (tenant_id, executable_step_id)
→ binding committed before backend call
```

```text
P5 StepResult = schema 1.1 historical
P6 StepResult = schema 1.2 current

non-NSL:
  business_operation_id = null
  operation_fingerprint = null

LOCAL_SKILL READ:
  business_operation_id = stable non-null
  operation_fingerprint = null
```

```text
eligible RuntimeJob selection
+ executor capability filter
+ lease CAS
= one claim transaction
```

```text
one DB-protected dispatcher leader per AE Runtime queue
bounded round
oldest runnable work + tenant_id tie-break
```

```text
timeline = deterministic read projection
no invented state history
unknown optional fields = null
```

## 6. Source Availability Gate

Current NSL v0.1 source baseline:

```text
nurigitdev/2608_nsl
803f22aadc3946a48b05472c80b60fe11d9d9554
```

P6-CA01 in the Codex implementation workspace must independently verify/materialize its actual checkout SHA before closure. A specific filesystem path is not normative.

Current workspace evidence records a clean NSL v0.1 checkout at the expected
`803f22a...` baseline. P6-CA01 must refresh that evidence at execution time.

## 7. Exit Shape

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
→ capability-aware AE Worker
→ VerifiedSkillArtifact
→ durable NSLStepExecutionBinding
→ SkillExecutionRequest
→ NSL READ Backend
→ NSLResultSummary
→ StepResult v1.2
→ AgentResult
```

No NSL WRITE, WC, blind replay or false publication success.
