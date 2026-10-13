# P5 Transition Implementation Baseline

**Status:** P5-CA01 REVIEWED PRE-IMPLEMENTATION BASELINE

**Phase:** P5 — Agent Planning & Execution Foundation

**Predecessor:** P4 Canonical Agent Runtime Foundation — implementation completed

**Successor:** P6 — NSL v0.2 READ Integration
**Target location:** `docs/transition/P5/`

---

## 1. Purpose

P5 fills the architectural layer between the P4 Agent Runtime and P6 NSL execution.

P4 established:

```text
PROMPT
→ ExecutionTrigger
→ AgentExecution
→ RuntimeJob
→ ExecutableStep
→ existing Chat/RAG
→ AgentResult
```

P5 adds:

```text
Natural-language Prompt
→ Intent Resolution
→ WorkIntent
→ Context Builder
→ AgentContext
→ Plan Builder
→ AgentPlan
→ Plan Validator
→ Deterministic Compiler
→ ExecutablePlan
→ ExecutableStep[]
→ Step Execution Engine
→ StepResult[]
→ AgentResult
```

P6 will then add:

```text
ExecutableStep(LOCAL_SKILL)
→ Skill Artifact Gateway
→ VerifiedSkillArtifact
→ NSL v0.2 READ
→ NSLResultSummary
→ StepResult
```

P5 MUST NOT call NSL.

---

## 2. Authority

```text
Frozen Platform v2.1 / Agent v2.1 / NSL v0.2
> P4 As-Built source and closure evidence
> P5-CA01 Frozen contract extraction and design closure
> P5 transition machine contracts
> P5 SRS
> P5 Architecture Decisions
> P5 Scope Review
> P5 Issue Register / planning and Prompt Registry traceability
> implementation convenience
```

Legacy JSON contracts under:

`docs/frozen/v2.1/10_PLATFORM_v2.1/04_LEGACY_REFERENCE_CONTRACTS/`

are useful implementation references only. They do not override Frozen Agent v2.1 DOCX semantics.

---

## 3. Required Frozen Reading

Before implementation, Codex SHALL read at minimum:

1. Agent Doc 01 — Unified Agent Loop / AgentExecution State Machine
2. Agent Doc 02 — Intent Resolution Detailed Design
3. Agent Doc 03 — Context Builder Detailed Design
4. Agent Doc 04 — Plan Builder Detailed Design
5. Agent Doc 05 — Plan Validator / Deterministic Compiler
6. Agent Doc 06 — StepExecutionEngine
7. Agent Doc 08 — Result Verification / Aggregation / Presentation
8. Agent Doc 10 — Integrated E2E Runtime Architecture
9. Agent Doc 99 — Unified Runtime and Memory Baseline
10. Platform AE detailed design
11. Platform Cross-System E2E design
12. P4 transition/implementation documents and current source

Reference-only machine-readable contracts:

- `99_work-intent-v1.schema.json`
- `99_agent-plan-v1.schema.json`
- `99_plan-step-v1.schema.json`

If a reference contract conflicts with the Frozen Agent documents, Frozen Agent wins.

---

## 4. P5 Document Set

Read in this order:

1. `README.md`
2. `P5_CA01_Frozen_Planning_Contract_Extraction_and_Pre_Implementation_Design_Closure_v1.0.md`
3. `contracts/README.md` and all `contracts/*.schema.json`
4. `P5_Architecture_Decisions_v1.0.md`
5. `P5_Agent_Planning_and_Execution_Foundation_SRS_v1.0.md`
6. `P5_Scope_Review_v1.0.md`
7. `P5_LLM_Prompt_Template_Registry_and_Governance_Design_v1.0.md`
8. `P5_Issue_Register_v1.0.md`
9. `P5_Intent_Context_Plan_Compiler_Traceability_v1.0.md`
10. `P5_LLM_Prompt_Registry_Traceability_v1.0.md`
11. current P4 As-Built source
12. `P5_Source_Audit_and_Implementation_Plan_v1.0.md`

The source extraction manifest is:

`P5_CA01_Frozen_Source_Manifest_v1.0.csv`

---

## 5. P5 Implementation Rule

> LLM/heuristic layers may propose intent and plan.
>
> Deterministic validation/compiler layers decide what becomes executable.
> Runtime executes only compiled ExecutablePlan/ExecutableStep contracts.

Do not implement P6+ scope to make P5 tests easier.

P5-CA01 is the closed design entry gate. P5-S1 and later slices SHALL use the
transition schemas under `contracts/` rather than silently treating legacy
`99_*` reference schemas as normative.

---

## 6. P5 Exit Shape

```text
PROMPT
→ AgentExecution
→ WorkIntent
→ AgentContext
→ AgentPlan
→ validation status=VALID
→ deterministic compile
→ ExecutablePlan
→ one or more ExecutableSteps
→ StepResults
→ AgentResult
```

At least one P5 acceptance scenario SHALL execute more than one Step.

No NSL invocation is permitted in P5.

---

## 7. P5-CA01 Closure

P5-CA01 completed the mandatory Frozen extraction and closed the
pre-implementation design questions for:

- exact WorkIntent, AgentContext, AgentPlan, validation, ExecutablePlan, and
  StepResult transition shapes;
- Frozen plan/step vocabulary and bounds;
- tenant-scoped immutable capability snapshots;
- P4 executable-step migration direction;
- canonical JSON hashing and immutable revision rules;
- clarification persistence with resume deferred;
- Prompt Registry immutability and enabled-stage acceptance scope.

This is a design closure only. P5 source and database implementation remain
`NOT STARTED` until P5-S1.
