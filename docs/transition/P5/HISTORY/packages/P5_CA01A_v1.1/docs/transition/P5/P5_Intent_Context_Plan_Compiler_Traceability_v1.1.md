# P5 Intent / Context / Plan / Compiler Traceability v1.1

**Status:** P5-CA01A TRACEABILITY BASELINE  
**Supersedes:** v1.0

## 1. Stage trace

| Stage | Main output | Deterministic control | CA01A addition |
|---|---|---|---|
| Intent Resolution | WorkIntent | existing IntentDecision adapter + schema/policy | legacy digest ↔ semantic hash interop |
| Context Build | AgentContext | trusted resolver + immutable context hash | unchanged |
| Plan Build | AgentPlan | deterministic profiles first | prompt digest fields remain bare; plan hash prefixed |
| Plan Validate | PlanValidationResult | LLM-free validator | exact runtime directive/state/phase mapping |
| Plan Compile | ExecutablePlan | exact capability snapshot + compiler | S-key / E-key / UUID separation |
| Step Execute | StepResult | durable RuntimeJob + executor contract | UUID runtime step + E-key lineage; WRITE fields null |
| Result Verify/Synthesis | AgentResult | completion criteria + StepResult evidence | unchanged |
| Prompt Control | Prompt Registry | immutable version/exact binding | history+pointer atomic transaction |

## 2. Identity trace

```text
AgentExecutionId (UUID)
  ↓
WorkIntentId (UUID)
  ↓
AgentContextId (UUID)
  ↓
AgentPlanId (UUID)
  ↓
LogicalPlanStepId (S1...)
  ↓ compile
CompiledStepKey (E1...)
  ↓ materialize
ExecutableStepId (UUID)
  ↓
StepResultId (UUID)
  ↓
AgentResultId (UUID)
```

`E1` is never the runtime `ExecutableStepId`.

## 3. Hash trace

### Existing/bare digests

```text
IntentDecision.decision_hash   = 64 hex
PromptVersion.content_sha256   = 64 hex
PromptRender.rendered_prompt_hash = 64 hex
PromptRender.output_hash       = 64 hex
```

### P5 semantic hashes

```text
WorkIntent.intent_hash               = sha256:<hex>
AgentContext.context_hash             = sha256:<hex>
CapabilitySnapshot.snapshot_hash      = sha256:<hex>
AgentPlan.plan_hash                   = sha256:<hex>
PlanValidationResult.result_hash      = sha256:<hex>
ExecutablePlan.executable_plan_hash   = sha256:<hex>
ExecutableStep.step_contract_hash     = sha256:<hex>
StepResult.result_hash                = sha256:<hex>
```

Shared utility converts representation without rehashing.

## 4. ExecutablePlan semantic trace

```text
Logical S1
→ Compiled E1
→ Runtime UUID A
```

Semantic dependency:

```text
E2.depends_on = [E1]
```

Runtime scheduler resolves E1/E2 to persisted UUID rows.

ExecutablePlan semantic hash excludes UUID A/B and uses E-key semantic content.

## 5. PlanValidation runtime mapping

| Validation | Directive | State | Phase | Compile? |
|---|---|---|---|---|
| VALID | PROCEED_TO_COMPILE | RUNNING | PLAN_COMPILE | yes |
| CLARIFICATION_REQUIRED | WAIT_FOR_INPUT | WAITING_INPUT | PLAN_VALIDATE | no |
| REPLAN_REQUIRED | BLOCK_REPLAN_REQUIRED | BLOCKED | PLAN_VALIDATE | no |
| CONTEXT_REFRESH_REQUIRED | BLOCK_CONTEXT_REFRESH_REQUIRED | BLOCKED | PLAN_VALIDATE | no |
| BLOCKED | BLOCK_EXECUTION | BLOCKED | PLAN_VALIDATE | no |
| INVALID_TERMINAL | FAIL_VALIDATION | FAILED | PLAN_VALIDATE | no |
| RETRYABLE_VALIDATION_FAILURE | RETRY_VALIDATION_BOUNDED | RUNNING | PLAN_VALIDATE | no until retry passes |

No P5 semantic auto-replan.

## 6. StepResult WRITE boundary

```text
P5 StepResult
business_operation_id = null
operation_fingerprint = null
```

P6 READ is expected to remain null.

Later WRITE phase must introduce a controlled contract change before non-null values are accepted.

## 7. Prompt activation trace

```text
PromptTemplateVersion immutable
            ↓
Binding change request
            ↓
lock/CAS current pointer
            ↓
INSERT binding history
+ UPDATE current pointer
            ↓
COMMIT
```

Already-running semantic execution uses captured exact version/hash and is isolated from later pointer changes.

## 8. P5 → P6 handoff

P6 SHALL reuse:

- AgentExecutionId
- WorkIntentId
- AgentContextId
- AgentPlanId
- ExecutablePlanId
- LogicalPlanStepId
- CompiledStepKey
- ExecutableStepId UUID
- StepResultId

P6 only adds a real `LOCAL_SKILL` executor binding to the existing execution model.
