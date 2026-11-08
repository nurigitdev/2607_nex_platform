# P5 Intent / Context / Plan / Compiler Traceability v1.0

**Status:** P5-CA01 REVIEWED PRE-IMPLEMENTATION TRACEABILITY BASELINE

---

## 1. Stage Traceability

| P5 Stage | Frozen Agent Source | P4/P5 Source Starting Point | P5 Output | P6 Dependency |
|---|---|---|---|---|
| Intent Resolution | Agent Doc 02 | `intent_policy.py`, `runtime_policy.py` | WorkIntent | capability/skill intent may later select LOCAL_SKILL |
| Base/Expanded Context | Agent Doc 03 | P4 AgentExecution, Conversation, owner scope, CX refs | AgentContext snapshot/hash | typed context projection into SkillExecutionRequest |
| Plan Build | Agent Doc 04 | no canonical implementation yet | AgentPlan | plan can contain NSL-bound local capability |
| Plan Validate | Agent Doc 05 | no canonical implementation yet | PlanValidationResult with Frozen status | NSL-bound step rejected unless exact capability exists |
| Plan Compile | Agent Doc 05 | P4 compatibility step materialization | ExecutablePlan + ExecutableStep[] | LOCAL_SKILL compiler binding |
| Step Execute | Agent Doc 06 | `executable_steps.py`, `runtime_jobs.py` | StepResult[] | NSLResultSummary → StepResult |
| Result Verify/Synthesis | Agent Doc 08 | `agent_results.py` | AgentResult | unchanged by NSL transport |
| Runtime State | Agent Doc 01 | `agent_execution.py` | phase/state trace | reused |
| Prompt Control | Platform AE DD + P5 Prompt Design | existing AE Prompt Registry | immutable version + exact execution provenance | reused by future LLM stages |

---

## 2. P4 As-Built → P5 Mapping

| P4 As-Built | P5 Treatment |
|---|---|
| `ExecutionTriggerV21` | reuse unchanged |
| `AgentExecution` | reuse; drive planning phases |
| `SqlAlchemyRuntimeJobQueue` | reuse; use START/CONTINUE for planning/step progression |
| `P4_CHAT_RAG_COMPATIBILITY` | retain as one executor/compatibility capability |
| `ae_executable_step` one-step restriction | generalize for multi-step plan |
| `CompatibilityChatRuntime` | wrap as executor adapter, not whole planning engine |
| `IntentDecision v1` | adapt to WorkIntent |
| `RuntimePolicy v1` | planning/context input; no competing planning authority |
| `AgentResultRepository` | invoke at plan terminalization rather than every intermediate step |
| PENDING `WORKSPACE_RESULT` | preserve |

---

## 3. Legacy Reference Contract Use

Reference-only:

```text
99_work-intent-v1.schema.json
99_agent-plan-v1.schema.json
99_plan-step-v1.schema.json
```

Useful reference concepts include:

- WorkIntent selectors/candidates/clarification
- PlanStep logical types `LOCAL_CAPABILITY / DELEGATE_WORK / AGGREGATE / REPORT`
- exact-version capability binding
- planner provenance
- step dependency/input binding
- user-safe rationale summary

Legacy plan kinds `ONE_STEP / DYNAMIC / TEMPLATE_BOUND` are not promoted into
P5. Frozen Agent Doc 04 controls the P5 transition vocabulary:

```text
DIRECT | CERTIFIED_BINDING | KNOWN_TEMPLATE | DYNAMIC
```

P5 SHALL NOT carry stale source/actor vocabulary such as direct
`EVENT`/`SCHEDULE` execution triggers into current Frozen runtime semantics.

Step8 final trigger vocabulary remains:

```text
PROMPT | CLAIMED_WORKITEM
```

P5 implements PROMPT/IA only.

Exact implementation-facing shapes are the P5-CA01 schemas under:

```text
docs/transition/P5/contracts/
```

---

## 4. Identity Trace

```text
AgentExecutionId
  ↓
WorkIntentId
  ↓
AgentContextId/version
  ↓
AgentPlanId/version
  ↓
PlanValidationId
  ↓
ExecutablePlanId
  ↓
LogicalPlanStepId
  ↓
ExecutableStepId
  ↓
StepResultId
  ↓
AgentResultId
```

Cross-cutting:

```text
correlation_id
causation_id
capability_snapshot_id/hash
plan_hash
executable_plan_hash
prompt_template_version_id/content_sha256/rendered_prompt_hash when an LLM stage is enabled
```

---

## 5. Runtime Phase Trace

| Phase | P5 Activity |
|---|---|
| `INTAKE` | P4 admission already complete |
| `BASE_CONTEXT` | establish safe principal/workspace/conversation references |
| `INTENT_RESOLUTION` | WorkIntent |
| `CONTEXT_EXPANSION` | AgentContext resolution/version |
| `PLAN_BUILD` | AgentPlan |
| `PLAN_VALIDATE` | deterministic validation |
| `PLAN_COMPILE` | ExecutablePlan materialization |
| `STEP_EXECUTION` | dependency-aware durable Step execution |
| `RESULT_VERIFY` | required StepResult/completion criteria checks |
| `RESULT_SYNTHESIS` | aggregate final semantic result |
| `RESULT_PUBLISH` | P4 AgentResult + PENDING delivery handoff |
| `FINALIZE` | not SUCCEEDED until publication ACK in later phase |

---

## 6. P5 Test Traceability

| Requirement Area | Minimum Evidence |
|---|---|
| WorkIntent | deterministic adapter, clarification, no fake entity IDs |
| AgentContext | version/hash repeatability, owner isolation |
| Plan Builder | four compatibility profiles, Frozen plan-kind vocabulary, multi-step profile |
| Validator | cycle/missing dependency/unsupported capability negative tests |
| Compiler | exact version, deterministic hash, no external calls |
| ExecutableStep | multiple steps per plan, P4 historical compatibility |
| Step Engine | restart/dedup/dependency order |
| StepResult | immutable result/ref handoff |
| AgentResult | created only after plan terminalization |
| Prompt Registry | insert-or-verify version immutability, explicit binding history, exact enabled-stage provenance |
| NSL boundary | LOCAL_SKILL unavailable and zero NSL invocations |

---

## 7. P5 → P6 Contract Handoff

P5 must expose stable interfaces equivalent to:

```text
CapabilityResolver.resolve(capability_id, version_constraint, snapshot)
→ ExactExecutorBinding

StepExecutor.execute(step, bound_inputs, context_refs)
→ StepResult
```

P6 will register an executor binding:

```text
LOCAL_SKILL
→ Skill Artifact Gateway
→ NSL READ
```

without changing WorkIntent/Plan/ExecutableStep/StepResult identities.

---

## 8. P5 Scope Classification

| Frozen concept | P5 treatment |
|---|---|
| IA + PROMPT | implemented |
| project-neutral prompt | implemented; no synthetic Project |
| `DIRECT`, `KNOWN_TEMPLATE` | implemented by deterministic profiles |
| `CERTIFIED_BINDING`, `DYNAMIC` | schema/resolver seam only |
| `LOCAL_CAPABILITY` | logical planning type; compiled only to current canonical compatibility binding |
| `AGGREGATE`, `REPORT` | bounded deterministic support |
| `DELEGATE_WORK` | schema-visible, rejected by P5 scope guard |
| `LOCAL_SKILL` | executable vocabulary reserved, unavailable until P6 |
| WC / CA / PA / EA | not implemented in P5 |
| WRITE / Human Approval / NSL | not implemented in P5 |

---

## 9. Initial Profile Trace

| Compatibility mode | Plan kind | Logical steps | Executable binding |
|---|---|---|---|
| `GENERAL_ANSWER` | `DIRECT` | `S1 LOCAL_CAPABILITY` | `CANONICAL_CAPABILITY/P4_CHAT_RAG_COMPATIBILITY` |
| `GROUNDED_ANSWER` | `KNOWN_TEMPLATE` | `S1 LOCAL_CAPABILITY -> S2 REPORT` | compatibility + deterministic report |
| `DOCUMENT_SUMMARY` | `KNOWN_TEMPLATE` | `S1 LOCAL_CAPABILITY -> S2 REPORT` | compatibility + deterministic report |
| `DOCUMENT_GENERATION` | `KNOWN_TEMPLATE` | `S1 LOCAL_CAPABILITY -> S2 REPORT(ARTIFACT)` | compatibility + deterministic report |
