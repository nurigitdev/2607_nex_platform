# P6 Agent ↔ NSL READ Integration Traceability v1.1

**Status:** P6-CA01 SOURCE-BACKED TRACEABILITY BASELINE

## 1. Identity chain

```text
correlation_id
→ AgentExecutionId
→ ExecutablePlanId
→ ExecutableStepId
→ NSLStepExecutionBinding
→ NSLExecutionId
→ BusinessOperationId
→ NSL ToolInvocationId(s)
→ StepResultId
→ AgentResultId
→ ResultDeliveryId
```

P6 READ has no WriteNodeId, WRITE IdempotencyKey or CommitState.

## 2. Responsibility trace

| Concern | Owner |
|---|---|
| AgentExecution / Plan / Step | AE |
| NSLExecutionId allocation/persistence | AE Integration |
| NSLExecutionId runtime lifecycle semantics | NSL Runtime |
| BusinessOperationId allocation/persistence | AE Integration |
| RuntimeJob / lease / attempt | AE |
| Worker/dispatcher | AE |
| Artifact lookup orchestration | Skill Artifact Gateway |
| Package/signature verification | NSL package/security boundary |
| LOCAL_SKILL executor | AE |
| deterministic READ execution | NSL |
| StepResult / AgentResult | AE |
| detailed NSL audit | NSL |
| timeline projection | AE protected operations surface |

## 3. Request mapping

| Canonical field | v0.1 backend |
|---|---|
| agent_execution_id | AE binding only |
| executable_plan_id | AE binding only |
| executable_step_id | AE binding only |
| nsl_execution_id | `SkillExecutionJob.execution_id` |
| business_operation_id | AE binding/timeline; v0.1 does not natively consume |
| skill_id | skill_id |
| exact_skill_version | skill_version |
| semantic hash | expected_semantic_hash |
| compiled inputs | StructuredInputs |
| input provenance | InputProvenance |
| principal | VerifiedPrincipalContext |
| data policy/classification | ExplicitDataHandlingPolicy + bounded context |
| context ref/hash | AE binding + bounded runtime context |
| correlation/causation | AE RuntimeJob/timeline |
| mode=NEW | ordinary v0.1 execute |

## 4. StepResult trace

```text
P5 historical result
schema=1.1
BOI=null
operation_fingerprint=null

P6 LOCAL_SKILL READ result
schema=1.2
BOI=stable non-null
operation_fingerprint=null
```

## 5. Claim trace

```text
worker capability declaration
→ dispatcher leader
→ candidate job
→ referenced step executor_kind
→ capability eligibility
→ lease CAS
```

All occur under one claim transaction for the final eligibility/update boundary.

## 6. Timeline trace

Projection ordering:

```text
event_time
phase_order
source_type_order
stable_source_id
```

Only canonical persisted/evidence-backed transitions are shown. Unknown optional historical state remains null.

## 7. Future WRITE preservation

P6 establishes:

```text
NSLExecutionId
BusinessOperationId
```

but not:

```text
WriteNodeId
ApprovalRequestId
IdempotencyKey
PayloadHash for WRITE
CommitState
VerificationStatus
```

Future phases extend rather than rename P6 identities.

## 8. P6-CA01 evidence

```text
P6_CA01_Source_Backed_READ_Contract_Closure_v1.0.md
contracts/*.schema.json
contracts/examples/p6-golden-*.json
tests/test_p6_ca01_read_contracts.py
```

This evidence closes contract traceability only. Runtime implementation and
PostgreSQL evidence remain assigned to P6-S0 through P6-S7.
