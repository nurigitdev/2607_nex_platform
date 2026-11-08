# P6 Agent ↔ NSL READ Integration Traceability v1.0

**Status:** PRE-IMPLEMENTATION TRACEABILITY BASELINE

---

## 1. End-to-End Identity Chain

```text
correlation_id
→ AgentExecutionId
→ ExecutablePlanId
→ ExecutableStepId
→ NSLExecutionId
→ BusinessOperationId
→ NSL ToolInvocationId(s)
→ StepResultId
→ AgentResultId
→ ResultDeliveryId
```

P6 READ has no WriteNodeId / IdempotencyKey / CommitState.

---

## 2. Component Trace

| P6 concern | Platform owner | NSL v0.1 reuse | Frozen v0.2 target |
|---|---|---|---|
| Worker lifecycle | AE | framework-neutral Skill worker inside backend | Agent/platform scheduling owner |
| RuntimeJob | AE | none | Agent owner |
| LOCAL_SKILL executor | AE | invokes stable API | Integration Layer |
| Skill resolution | Skill Gateway / adapter | VerifiedPackageSkillResolver | exact artifact resolution |
| Package verification | NSL security/package adapter | NspVerifier + signature | PackageTrustEvidence |
| Request | Integration layer | SkillExecutionJob adapter | SkillExecutionRequest |
| Runtime execution | NSL | RuntimeEngine | RuntimeEngine |
| Tool READ | NSL + provider adapter | ToolExecutionPort | read tool port |
| Result | Integration layer | RuntimeResultEnvelope | ExecutionResult → NSLResultSummary |
| StepResult | AE | mapped | Agent semantic result |
| Detailed audit | NSL | audit/snapshot | NSL evidence SoR |
| Timeline | AE | refs only | Agent history/operations |

---

## 3. Request Field Mapping

| Canonical P6 / v0.2 field | v0.1 backend mapping |
|---|---|
| `agent_execution_id` | retained in AE invocation binding |
| `executable_plan_id` | retained in AE invocation binding |
| `executable_step_id` | retained in AE invocation binding |
| `nsl_execution_id` | `SkillExecutionJob.execution_id` |
| `business_operation_id` | retained in AE binding/trace; v0.1 READ does not natively require it |
| `tenant_id` | principal/runtime scope |
| `skill_id` | `skill_id` |
| `exact_skill_version` | `skill_version` |
| semantic hash | `expected_semantic_hash` |
| `compiled_inputs` | `StructuredInputs` |
| input provenance | `InputProvenance` |
| explicit resources | bounded adapter projection |
| executing principal | `VerifiedPrincipalContext` |
| data classification | `ExplicitDataHandlingPolicy` / bounded context |
| context ref/hash | AE binding + bounded runtime context |
| correlation/causation | AE RuntimeJob/timeline |
| `mode=NEW` | v0.1 ordinary execute |
| resume | not used in P6 READ |

---

## 4. Result Mapping Trace

```text
RuntimeResultEnvelope
→ ExecutionResult
→ P6 NSLResultSummary
→ StepExecutionOutcome
→ StepResult
```

No LLM explanation may mutate the deterministic NSL result.

---

## 5. P6 READ Security Trace

```text
exact capability
→ exact skill/version
→ exact NSP
→ package verification
→ signature/trust policy
→ semantic hash check
→ verified artifact
→ NSL runtime
```

Every failure before runtime implies provider/Tool invocation count = 0.

---

## 6. P6 → Future WRITE Preservation

P6 deliberately establishes identities needed later:

```text
NSLExecutionId
BusinessOperationId
```

but does not establish:

```text
WriteNodeId
IdempotencyKey
PayloadHash for WRITE
ApprovalRequestId
CommitState
VerificationStatus
```

Future WRITE extends, not renames, the P6 identities.
