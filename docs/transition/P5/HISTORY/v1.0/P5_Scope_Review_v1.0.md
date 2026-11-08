# P5 Agent Planning & Execution Foundation Scope Review v1.0

**Status:** P5-CA01 REVIEWED PRE-IMPLEMENTATION SCOPE

---

## 1. Why P5 Exists

P4 proved the runtime shell but executes the existing Chat/RAG path through one compatibility step.

That is not yet the full Agent v2.1 planning loop.

P5 adds the missing transformation:

```text
natural language
→ structured intent/context
→ logical plan
→ deterministic executable plan
→ multiple durable steps
```

P6 then connects one step category to NSL.

---

## 2. What P5 Must Not Become

P5 is not:

- a general autonomous Agent project;
- an NSL integration phase;
- a WC/multi-agent phase;
- a WRITE/Approval phase;
- a complete LLM planner optimization project;
- a replacement of existing Chat/RAG.

---

## 3. P4 Structures Reused

P5 SHALL reuse:

- `ae_agent_execution`
- `ae_runtime_job`
- `ae_runtime_job_attempt`
- `ae_executable_step`
- `ae_agent_result`
- `ae_result_delivery`
- Conversation/Interaction
- `ChatApplicationService`
- existing intent/runtime policy
- CX/MO service boundaries

P5 must generalize `ae_executable_step`, because P4 intentionally restricted it to one `P4_CHAT_RAG_COMPATIBILITY` row per execution.

---

## 4. Minimum Production-Capable Planning

P5 closure does not require a free-form LLM planner.

Mandatory production path:

```text
existing deterministic intent
→ canonical WorkIntent
→ context snapshot
→ deterministic/template plan
→ validator
→ compiler
→ durable step engine
```

This provides a deterministic baseline before model-generated dynamic planning.

---

## 5. LLM Boundaries

LLM-assisted Intent/Plan generation is optional in P5.

If implemented:

- output is candidate data;
- no stable entity authority;
- no direct execution;
- no private chain-of-thought persistence;
- same deterministic validator/compiler is mandatory;
- shadow rollout is preferred first.

Every enabled LLM stage uses the existing AE RDBMS Prompt Registry with an
exact immutable template version and execution provenance. Deterministic stages
do not resolve unused prompt purposes. Prompt Registry immutability hardening is
mandatory in P5-S1 even though optional LLM intent/dynamic planning remains off.

---

## 6. Multi-Step Closure

P5 SHALL prove true multi-step persistence/execution.

Minimum acceptable pattern:

```text
Step A: existing compatibility/local capability
→ StepResult A
→ Step B: deterministic report/aggregation
→ StepResult B
→ AgentResult
```

P5 SHOULD split retrieval/model into separate steps only if the source refactor is safe.

Do not jeopardize v1 regression merely to make a prettier plan diagram.

---

## 7. Clarification

Clarification is part of P5 intent/context correctness.

At minimum, P5 must be able to stop at `WAITING_INPUT` with explicit questions and zero execution side effects.

Clarification resume is explicitly deferred from P5. P5 persists the wait and
questions but does not add a `RESUME_EXECUTION` job type or mutate the waiting
WorkIntent.

---

## 8. P6 Boundary

P5 may define/recognize an NSL-bound executor category but cannot execute it.

Acceptance includes a negative case proving NSL is never invoked.

---

## 9. P5 Closure Statement

The proper closure statement is:

> **P5 Agent Planning & Execution Foundation — intent/context/plan/compiler/multi-step execution CLOSED**

It is not:

> Full NeX Agent v2.1 implementation complete.
