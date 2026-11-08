# P5 — NeX Agent Planning & Execution Foundation SRS v1.1

**Document Status:** P5-CA01A REVIEWED IMPLEMENTATION BASELINE  
**Supersedes:** P5 SRS v1.0  
**Predecessor:** P4 Canonical Agent Runtime Foundation  
**Successor:** P6 NSL v0.2 READ Integration

---

# 1. Purpose

P5 implements:

```text
Natural-language Prompt
→ WorkIntent
→ AgentContext
→ AgentPlan
→ PlanValidationResult
→ deterministic ExecutablePlan
→ durable ExecutableStep[]
→ StepResult[]
→ AgentResult
```

P5 SHALL prove one AgentExecution with 2+ persisted steps.

P5 SHALL NOT call NSL.

---

# 2. P4 As-Built reuse

P5 extends, not replaces:

- `AgentExecutionId` and Frozen state/phase vocabulary;
- `ae_runtime_job` / attempts;
- P4 RuntimeJob START/CONTINUE semantics;
- P4 UUID `ExecutableStepId` identity;
- `ChatApplicationService` compatibility behavior;
- AgentResult + PENDING WORKSPACE_RESULT delivery;
- project-neutral IA prompt admission.

---

# 3. Identity model

```text
WorkIntentId          = UUID
AgentContextId        = UUID
AgentPlanId           = UUID
PlanValidationId      = UUID
ExecutablePlanId      = UUID
LogicalPlanStepId     = S1, S2, ...
CompiledStepKey       = E1, E2, ...
ExecutableStepId      = UUID
StepResultId          = UUID
AgentResultId         = UUID
```

Mandatory separation:

```text
LogicalPlanStepId != CompiledStepKey
CompiledStepKey   != ExecutableStepId
ExecutableStepId  remains compatible with P4 UUID identity
```

`CompiledStepKey` is semantic/plan-local. `ExecutableStepId` is runtime/persistence identity.

---

# 4. Hash interoperability

P5 defines two hash representations.

## 4.1 Bare SHA-256 digest

```text
^[0-9a-f]{64}$
```

Used for legacy/existing fields explicitly named as digest, including Prompt Registry:

- `content_sha256`
- `prompt_content_sha256`
- existing `rendered_prompt_hash`
- existing IntentDecision `decision_hash`
- existing prompt render `output_hash`

## 4.2 Semantic hash reference

```text
^sha256:[0-9a-f]{64}$
```

Used for P5 semantic object hashes:

- `intent_hash`
- `context_hash`
- `capability_snapshot_hash`
- `plan_hash`
- PlanValidation `result_hash`
- `executable_plan_hash`
- `step_contract_hash`
- StepResult `result_hash`

## 4.3 Conversion

One shared utility SHALL implement representation conversion.

Conversion SHALL NOT hash an existing digest again.

---

# 5. WorkIntent

P5 SHALL implement immutable/revisioned WorkIntent.

Mandatory semantics:

- source is current IA `PROMPT` only;
- Frozen runtime mode is `INTERACTIVE`;
- current product execution mode is carried separately;
- selectors/parameter candidates are non-authoritative;
- Project may remain unresolved/null;
- clarification is explicit;
- existing IntentDecision is the mandatory initial deterministic resolver;
- raw prompt is not duplicated into WorkIntent;
- provenance stores existing bare decision digest and optional prompt provenance.

Changed intent creates a new immutable `intent_revision`; no in-place edit.

---

# 6. Clarification

If required information is unresolved:

```text
AgentExecution.state = WAITING_INPUT
phase = INTENT_RESOLUTION or CONTEXT_EXPANSION
```

No executable steps or provider/business side effects are created.

Clarification resume/re-intent is deferred beyond P5.

---

# 7. AgentContext

AgentContext is an immutable generation snapshot.

It may contain bounded:

- tenant/principal/IA refs;
- workspace/conversation/interaction refs;
- authoritative Project/entity refs when resolved;
- retrieval/evidence refs;
- runtime-policy refs;
- conflict/degradation metadata;
- context manifest and token budget;
- semantic context hash.

It SHALL NOT contain raw prompt/document bodies, credentials, provider endpoints, API keys, hidden reasoning or cross-service DB snapshots.

---

# 8. Capability snapshot

P5 SHALL use a tenant-scoped immutable exact-version capability snapshot.

Initial internal capabilities:

```text
AE.CHAT.COMPATIBILITY
AE.RESULT.REPORT
```

No implicit `latest` resolution.

`LOCAL_SKILL` remains future executable vocabulary and is unavailable until P6.

---

# 9. AgentPlan

Frozen/P5 plan kinds:

```text
DIRECT
CERTIFIED_BINDING
KNOWN_TEMPLATE
DYNAMIC
```

P5 deterministic profiles use `DIRECT` and `KNOWN_TEMPLATE`.

Logical step types:

```text
LOCAL_CAPABILITY
DELEGATE_WORK
AGGREGATE
REPORT
```

Bounds:

```text
max_plan_steps = 12
max_delegation_depth = 0
max_parallel_steps = 1
max_auto_replan = 0
```

AgentPlan is immutable and never directly executable.

---

# 10. Prompt Registry

The existing AE RDBMS Prompt Registry is the only runtime prompt authority for enabled LLM stages.

Mandatory:

- PromptTemplateVersion immutable insert-or-verify;
- no implicit latest;
- exact version/hash provenance;
- source seeds bootstrap only;
- binding change is atomic history+pointer transaction;
- concurrent binding change uses row lock or expected-current CAS;
- already-running semantic artifacts keep captured version/hash.

Optional LLM Intent/Dynamic Plan Builder remains disabled by default and is not required for P5 closure.

---

# 11. Plan Validation

Validation is deterministic and LLM-free.

Statuses:

```text
VALID
REPLAN_REQUIRED
CONTEXT_REFRESH_REQUIRED
CLARIFICATION_REQUIRED
BLOCKED
INVALID_TERMINAL
RETRYABLE_VALIDATION_FAILURE
```

Every result SHALL include a required `runtime_directive` constrained by status.

Mapping:

| Status | Directive | State | Phase |
|---|---|---|---|
| `VALID` | `PROCEED_TO_COMPILE` | `RUNNING` | `PLAN_COMPILE` |
| `CLARIFICATION_REQUIRED` | `WAIT_FOR_INPUT` | `WAITING_INPUT` | `PLAN_VALIDATE` |
| `REPLAN_REQUIRED` | `BLOCK_REPLAN_REQUIRED` | `BLOCKED` | `PLAN_VALIDATE` |
| `CONTEXT_REFRESH_REQUIRED` | `BLOCK_CONTEXT_REFRESH_REQUIRED` | `BLOCKED` | `PLAN_VALIDATE` |
| `BLOCKED` | `BLOCK_EXECUTION` | `BLOCKED` | `PLAN_VALIDATE` |
| `INVALID_TERMINAL` | `FAIL_VALIDATION` | `FAILED` | `PLAN_VALIDATE` |
| `RETRYABLE_VALIDATION_FAILURE` | `RETRY_VALIDATION_BOUNDED` | `RUNNING` | `PLAN_VALIDATE` |

Technical validation retry reuses the same AgentPlan and never triggers semantic LLM replan.

---

# 12. Deterministic Compiler

Only `VALID` AgentPlan can compile.

Compiler SHALL bind exact:

- WorkIntent ref/hash;
- AgentContext ref/hash;
- Capability snapshot ref/hash;
- validation result;
- compiler version.

It SHALL create immutable ExecutablePlan and plan-local `CompiledStepKey` values.

It SHALL also allocate/materialize UUID `ExecutableStepId` values compatible with P4.

Compiler MUST NOT call model/provider/tool/NSL.

Identical semantic inputs produce identical semantic ExecutablePlan hash; runtime UUIDs are excluded from this semantic hash.

---

# 13. ExecutablePlan / ExecutableStep

ExecutablePlan step record includes both:

```text
compiled_step_key = E1...
executable_step_id = UUID
```

Dependencies and semantic completion references use `compiled_step_key`.

Runtime DB rows use `executable_step_id` UUID as durable identity and store `compiled_step_key` for deterministic lineage.

P5-S5 SHALL generalize P4 `ae_executable_step` without changing historical P4 UUID identities.

---

# 14. StepResult

Every terminal materialized step produces one immutable StepResult.

Required lineage:

```text
StepResultId
AgentExecutionId
ExecutablePlanId
ExecutableStepId UUID
CompiledStepKey E1...
LogicalPlanStepId S1...
attempt_no
status
result contract/payload refs
artifact/evidence/external refs
result_hash
```

P5 WRITE guard:

```text
business_operation_id = null
operation_fingerprint = null
```

Both fields are required in the v1.1 P5 contract and MUST be null.

Non-null causes contract validation failure before persistence.

---

# 15. Step Execution Engine

P5 engine:

- schedules from persisted plan/step/result state;
- executes one deterministic ready step at a time;
- never re-executes a succeeded terminal step after restart;
- uses RuntimeJob START/CONTINUE;
- propagates failed/blocked dependency outcomes deterministically;
- fails closed for unavailable executor;
- does not execute DELEGATE_WORK or LOCAL_SKILL.

---

# 16. Minimum plan profiles

```text
GENERAL_ANSWER
DIRECT:
S1 LOCAL_CAPABILITY(AE.CHAT.COMPATIBILITY)
```

```text
GROUNDED_ANSWER
KNOWN_TEMPLATE:
S1 LOCAL_CAPABILITY(AE.CHAT.COMPATIBILITY)
→ S2 REPORT(INTERACTIVE_RESPONSE)
```

```text
DOCUMENT_SUMMARY
KNOWN_TEMPLATE:
S1 LOCAL_CAPABILITY(AE.CHAT.COMPATIBILITY)
→ S2 REPORT(INTERACTIVE_RESPONSE)
```

```text
DOCUMENT_GENERATION
KNOWN_TEMPLATE:
S1 LOCAL_CAPABILITY(AE.CHAT.COMPATIBILITY)
→ S2 REPORT(ARTIFACT)
```

The deterministic report executor SHALL not add an unplanned LLM call.

---

# 17. AgentResult

Intermediate StepResult never creates final AgentResult.

Finalization:

```text
required StepResult set complete
→ completion criteria verification
→ result synthesis/projection
→ immutable AgentResult
→ existing required WORKSPACE_RESULT delivery PENDING
```

AgentExecution remains not `SUCCEEDED` until later publication ACK.

---

# 18. Persistence / migrations

Recommended sequence:

```text
2100_ae_prompt_registry_hardening.sql
2101_ae_work_intent.sql
2102_ae_agent_context.sql
2103_ae_capability_plan_validation.sql
2104_ae_executable_plan.sql
2105_ae_executable_step_planning.sql
2106_ae_step_result.sql
```

### 2100

- immutable prompt-version insert/verify behavior at repository layer;
- `ae_prompt_binding_history` table;
- indexes/constraints for transactional binding change.

### 2105

- preserve P4 UUID `executable_step_id`;
- add `compiled_step_key`;
- remove P4 one-step-only constraints;
- add P5 plan/logical/dependency fields;
- new P5 rows enforce completeness; historical P4 rows remain readable.

---

# 19. Rollout

```text
NEX_AE_PLANNING_MODE=disabled|shadow|required
```

`disabled`: P4 response-authoritative behavior.  
`shadow`: build/validate/compile evidence without extra side effects.  
`required`: WorkIntent/Context/Plan/VALID/ExecutablePlan required before execution.

---

# 20. Required CA01A tests

- UUID ExecutableStep identity retained from P4;
- compiled keys deterministic and unique within plan;
- semantic plan hash unchanged when runtime UUIDs differ;
- bare SHA ↔ semantic hash conversion round-trip;
- no double hashing;
- every validation status maps to expected runtime directive/state/phase;
- no LLM call on `REPLAN_REQUIRED`;
- retryable validation obeys bounded technical retry;
- StepResult non-null WRITE fields rejected;
- prompt binding history/pointer transaction fault rollback;
- concurrent binding activation conflict protection;
- in-flight prompt snapshot unaffected by later binding switch.

---

# 21. P5 Exit Gate

One real AgentExecution demonstrates:

```text
Prompt
→ WorkIntent
→ AgentContext
→ AgentPlan
→ validation VALID
→ ExecutablePlan
→ 2+ persisted UUID ExecutableSteps with E-key lineage
→ ordered durable execution
→ StepResults with null WRITE fields
→ AgentResult
```

with P4 regression PASS, restart safety, no fake IDs, no WC, no NSL, and no false SUCCEEDED.
