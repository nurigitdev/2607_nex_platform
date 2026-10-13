# P5-CA01 Frozen Planning Contract Extraction and Pre-Implementation Design Closure v1.0

**Status:** APPROVED PRE-IMPLEMENTATION CLOSURE

**Phase:** P5 - Agent Planning and Execution Foundation

**Decision date:** 2026-10-13
**Authority layer:** P5 transition interpretation over the unchanged v2.1 Frozen baseline and approved P4-CA01 amendment

## 1. Purpose

P5-CA01 closes the design gaps that remained after the two LLM Prompt Registry
documents were added to the original P5 document set. It also extracts the
Frozen planning semantics needed before P5 feature implementation starts.

This closure does not alter any file under `docs/frozen/v2.1/`.

## 2. Authority

The applicable authority order is:

```text
Integrated Frozen v2.1 baseline
> approved P4-CA01 project-neutral PROMPT amendment
> P5-CA01 transition contract extraction and decisions
> remaining P5 design documents
> legacy reference JSON schemas
> implementation convenience
```

The legacy `99_work-intent-v1`, `99_agent-plan-v1`, and `99_plan-step-v1`
schemas remain reference material. Their stale trigger and plan-kind vocabulary
does not override the Frozen Agent documents.

The exact Frozen inputs and hashes reviewed by this closure are recorded in
`P5_CA01_Frozen_Source_Manifest_v1.0.csv`.

## 3. Bounded P5 Scope

P5 implements the project-neutral IA/PROMPT planning foundation for the current
Chat/RAG product surface.

```text
PROMPT + IA
project_id = null | authoritative non-empty Project reference
```

`project_id=null` is valid for all four current compatibility modes unless a
specific intent or capability requires Project authority. P5 must not create a
default, personal, Workspace, Conversation, generated, or mock Project.

P5 does not:

- create WC WorkItems;
- execute `DELEGATE_WORK`;
- call NSL;
- execute `LOCAL_SKILL`;
- perform WRITE;
- implement CA/PA/EA background execution;
- add Enterprise OS or Project Agent dependencies.

Those Frozen concepts remain reserved vocabulary and are not silently removed
from the future architecture.

## 4. Extracted Contract Decisions

### CA01-DEC-01 - WorkIntent transition contract

The P5 envelope is `p5-work-intent-v1.schema.json`.

It uses the Frozen semantic names `work_intent_id` and `execution_id`, accepts
only `source.source_type=PROMPT`, and preserves the following distinctions:

- `execution_mode=INTERACTIVE` describes the Frozen Agent runtime mode;
- `compatibility_execution_mode` carries the current product mode
  `GENERAL_ANSWER | GROUNDED_ANSWER | DOCUMENT_SUMMARY | DOCUMENT_GENERATION`;
- selectors and parameter candidates are non-authoritative;
- Project is optional until a trusted resolver establishes it;
- clarification is explicit and blocks planning when `status=REQUIRED`;
- raw prompt content is owned by Conversation/Interaction and is not duplicated
  into WorkIntent.

Current `IntentDecision v1` is the mandatory first deterministic resolver. Its
decision hash and rule output are captured in WorkIntent provenance.

### CA01-DEC-02 - WorkIntent revision and idempotency

WorkIntent is insert-only. The active binding is unique per:

```text
(tenant_id, agent_execution_id, intent_revision)
```

Revision `1` is the initial decision. A later clarification/re-intent creates a
new row and explicit predecessor reference; it never updates the prior envelope.
P5 closure persists revision 1 and clarification waits. Resume/re-intent is
reserved and is not implemented by P5.

### CA01-DEC-03 - AgentContext transition contract

The P5 envelope is `p5-agent-context-v1.schema.json`.

AgentContext is an immutable generation snapshot. It contains bounded identity,
Workspace/Conversation/Interaction references, optional authoritative Project
and entity references, evidence/retrieval references, policy references,
conflicts, degradations, manifest entries, and a content hash.

It must not contain raw prompt text, retrieved document bodies, credentials,
provider endpoints, API keys, hidden reasoning, or cross-service DB snapshots.

The active binding is unique per:

```text
(tenant_id, agent_execution_id, context_generation)
```

### CA01-DEC-04 - Capability snapshot ownership

P5 uses a tenant-scoped immutable capability snapshot. Platform-global
deduplication is an optimization and is not part of P5.

Every AgentPlan references one exact snapshot ID, version, and hash. There is no
implicit `latest` lookup during validation, compilation, retry, or restart.

The first internal capability IDs are:

| Capability ID | Logical type | P5 executable type | Executor binding |
|---|---|---|---|
| `AE.CHAT.COMPATIBILITY` | `LOCAL_CAPABILITY` | `CANONICAL_CAPABILITY` | `P4_CHAT_RAG_COMPATIBILITY` |
| `AE.RESULT.REPORT` | `REPORT` | `REPORT` | `DETERMINISTIC_REPORT` |

These are internal P5 vocabulary, not a public external API.

### CA01-DEC-05 - AgentPlan and PlanStep vocabulary

The P5 envelope is `p5-agent-plan-v1.schema.json`.

Frozen plan kinds are:

```text
DIRECT
CERTIFIED_BINDING
KNOWN_TEMPLATE
DYNAMIC
```

Frozen logical step types are:

```text
LOCAL_CAPABILITY
DELEGATE_WORK
AGGREGATE
REPORT
```

`DELEGATE_WORK` remains schema-visible but is rejected by the P5 scope guard.
An AgentPlan is immutable, cannot invoke an endpoint, and is never executable
without a persisted valid PlanValidationResult and deterministic compilation.

### CA01-DEC-06 - Planning bounds

P5 fixes the following first-closure bounds:

```text
max_plan_steps = 12
max_delegation_depth = 0
max_parallel_steps = 1
max_capability_hints = 8
max_entity_selectors = 32
max_parameter_candidates = 64
max_completion_criteria = 16
max_clarification_questions = 8
```

The plan may represent a DAG, but the engine selects exactly one ready step in
deterministic serial order.

### CA01-DEC-07 - Deterministic plan profiles

| Compatibility mode | Plan kind | Logical shape |
|---|---|---|
| `GENERAL_ANSWER` | `DIRECT` | `S1 LOCAL_CAPABILITY(AE.CHAT.COMPATIBILITY)` |
| `GROUNDED_ANSWER` | `KNOWN_TEMPLATE` | `S1 LOCAL_CAPABILITY -> S2 REPORT(INTERACTIVE_RESPONSE)` |
| `DOCUMENT_SUMMARY` | `KNOWN_TEMPLATE` | `S1 LOCAL_CAPABILITY -> S2 REPORT(INTERACTIVE_RESPONSE)` |
| `DOCUMENT_GENERATION` | `KNOWN_TEMPLATE` | `S1 LOCAL_CAPABILITY -> S2 REPORT(ARTIFACT)` |

The compatibility executor may internally use existing AE/CX/MO behavior. P5
does not pretend that the internal retrieval/model calls are separate durable
steps until a later safe refactor explicitly makes them so.

### CA01-DEC-08 - Validation vocabulary

The P5 envelope is `p5-plan-validation-result-v1.schema.json`.

Frozen statuses are:

```text
VALID
REPLAN_REQUIRED
CONTEXT_REFRESH_REQUIRED
CLARIFICATION_REQUIRED
BLOCKED
INVALID_TERMINAL
RETRYABLE_VALIDATION_FAILURE
```

The validator is LLM-free. P5 additionally rejects `DELEGATE_WORK`, WRITE,
`LOCAL_SKILL`, unresolved required authority, unsupported capability bindings,
cycles, missing dependencies, invalid input bindings, and plans over 12 steps.

### CA01-DEC-09 - ExecutablePlan and step vocabulary

The P5 envelope is `p5-executable-plan-v1.schema.json`.

Frozen executable step types are:

```text
LOCAL_SKILL
CANONICAL_CAPABILITY
DELEGATE_WORK
HUMAN_CONFIRMATION
FORMAL_APPROVAL
AGGREGATE
REPORT
```

P5 can materialize only `CANONICAL_CAPABILITY`, `AGGREGATE`, and `REPORT`.
`LOCAL_SKILL` is a P6 handoff seam and must fail validation/compilation with
`EXECUTOR_NOT_AVAILABLE` before any step becomes READY.

### CA01-DEC-10 - StepResult semantics

The P5 envelope is `p5-step-result-v1.schema.json`.

One immutable StepResult represents one terminal semantic outcome for a
materialized step. Waiting and retry attempts are stored as runtime state and
attempt evidence, not as a final StepResult.

P5 terminal StepResult statuses are:

```text
SUCCEEDED
FAILED
BLOCKED
CANCELLED
```

An executor outcome is schema/contract validated before a `SUCCEEDED`
StepResult is accepted.

### CA01-DEC-11 - Canonical hash profile

P5 hashes use:

```text
SHA-256(
  UTF-8(
    JSON serialize with sort_keys=true,
    separators=(",", ":"),
    ensure_ascii=false,
    allow_nan=false
  )
)
```

The stored representation is `sha256:<64 lowercase hex>`.

Each contract defines a semantic hash projection that excludes its own hash,
database timestamps, and generated row identity while retaining semantic
version and upstream ID/hash bindings. Set-like arrays must be normalized before
hashing; ordered step/dependency arrays retain order.

### CA01-DEC-12 - Prompt Registry scope and immutability

The existing AE Prompt Registry is the only P5 prompt registry.

P5 deterministic intent and plan profiles do not require an LLM. Therefore:

- an LLM stage is optional and disabled by default;
- every LLM stage that is enabled in P5 must resolve an exact active binding and
  immutable version from the RDBMS registry;
- deterministic stages do not resolve unused prompt purposes;
- the registry must support the future purposes without making them active.

`ae_prompt_template_versions` changes from mutable UPSERT behavior to
insert-or-verify behavior. A conflict with identical immutable content is
idempotent; a conflict with different content/hash is rejected. Binding changes
remain explicit mutable deployment pointers, but every change records history.
Retry/resume reuses captured prompt version/hash unless an explicit new semantic
attempt records new provenance.

Prompt Registry hardening is part of P5-S1, before any optional LLM planning
mode can be enabled.

### CA01-DEC-13 - Clarification closure

P5 persists:

- WorkIntent with `clarification.status=REQUIRED`;
- reason codes and bounded user-safe questions;
- `AgentExecution.state=WAITING_INPUT`;
- current phase and privacy-safe provenance;
- zero executable steps and zero provider/business side effects.

P5 does not add `RESUME_EXECUTION` to the P4 RuntimeJob vocabulary. Clarification
resume/re-intent is deferred to a later controlled slice. `START_EXECUTION` and
`CONTINUE_EXECUTION` remain the only P5 job types.

### CA01-DEC-14 - P4 executable-step migration

Migration 2105 will:

1. preserve every P4 row and identity;
2. remove the P4-only `step_kind` CHECK and per-execution-kind uniqueness;
3. retain the value `P4_CHAT_RAG_COMPATIBILITY` as executor binding vocabulary;
4. add nullable historical fields for executable plan, logical step, step type,
   ordering, dependencies, contracts, and step hash;
5. require all new P5 rows to have plan/logical/type/order/hash bindings;
6. add deterministic uniqueness by executable plan and step index plus semantic
   materialization identity;
7. make legacy-interaction binding optional only for non-compatibility steps;
8. use a behaviorally equivalent SQLite table rebuild for fast regression.

The detailed DDL remains an implementation responsibility of P5-S5 and must be
verified against both historical P4 rows and fresh P5 rows.

### CA01-DEC-15 - Result finalization

Intermediate steps never create AgentResult. Plan completion requires all
required terminal steps to succeed, no unresolved wait/reconciliation, and
completion criteria verification.

```text
StepResult[] complete
-> completion verification
-> immutable AgentResult
-> required PENDING ResultDelivery
```

P4's no-false-success rule is preserved: AgentExecution is not `SUCCEEDED`
while a required ResultDelivery lacks durable acknowledgement.

## 5. Prompt Document Reconciliation

The two Prompt Registry documents are normative P5 transition documents and are
part of the README read order.

Their acceptance language is interpreted as follows:

```text
"production LLM stages"
= LLM-dependent stages actually enabled by the selected P5 runtime mode
```

It does not require P5 to enable the optional LLM Intent Resolver or Dynamic
Plan Builder. It does require exact registry resolution and provenance for any
LLM stage that is enabled, including existing response generation.

## 6. Pre-Implementation Issue Closure

P5-CA01 closes P5-ISSUE-001, 002, 003, 004, 005, 006, 007, 009, and 013 at the
design level. It also closes the late Prompt Registry integration gap.

Implementation evidence is still required in the owning P5 slices. A design
closure is not a claim that migrations or runtime code already exist.

## 7. P5 Slice Entry Rule

P5-S1 may begin only from this reviewed baseline. Each implementation slice
must use the transition schemas under `docs/transition/P5/contracts/` and must
not silently reinterpret legacy reference schemas.

P5-S1 includes:

- shared transition contract validation/hash utilities;
- WorkIntent deterministic adapter and persistence;
- Prompt Registry immutable insert-or-verify behavior;
- binding history and exact execution-stage prompt provenance foundation.

All later slices retain the existing P5-S2 through P5-S9 sequence.

## 8. Closure Statement

P5-CA01 is closed when:

- Frozen source hashes are recorded and unchanged;
- exact P5 transition schemas validate;
- legacy/Frozen vocabulary differences are explicit;
- Prompt Registry acceptance and implementation ownership are explicit;
- all pre-implementation P1 issues have concrete decisions;
- no P5 source feature or migration is falsely claimed as implemented.

> P5-CA01 closes the design entry gate. It does not close P5 implementation.
