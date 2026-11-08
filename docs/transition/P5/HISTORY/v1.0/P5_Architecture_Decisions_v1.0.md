# P5 Architecture Decisions v1.0

**Status:** P5-CA01 REVIEWED DESIGN BASELINE

---

## P5-DEC-01 — Planning is a separate canonical layer

P5 SHALL NOT hide intent/context/plan logic inside `chat.py`, `runtime_policy.py`, or one compatibility step.

Canonical separation:

```text
Prompt
→ WorkIntent
→ AgentContext
→ AgentPlan
→ Validation
→ ExecutablePlan
→ ExecutableStep
```

---

## P5-DEC-02 — WorkIntent is structured and non-authoritative for unresolved entities

Natural-language interpretation may produce:

- intent label/class
- goal
- capability hints
- entity selectors
- parameter candidates
- constraints
- completion criteria
- clarification requirement

It MUST NOT manufacture authoritative business entity IDs.

Stable Project/Business references come only from deterministic/trusted resolvers.

---

## P5-DEC-03 — Existing v1 intent policy is reused as the first deterministic Intent Resolver

Current P4/v1 behavior:

```text
GENERAL_ANSWER
GROUNDED_ANSWER
DOCUMENT_SUMMARY
DOCUMENT_GENERATION
```

is not discarded.

P5 SHALL adapt it into canonical WorkIntent for the first implementation wave.

An LLM-assisted IntentCandidate MAY be added behind an interface/feature flag, but is not required for P5 closure.

---

## P5-DEC-04 — Context is immutable snapshot/reference based

AgentContext SHALL be an immutable or versioned snapshot with:

- tenant/principal/agent refs
- workspace/conversation refs
- resolved business/project refs when authoritative
- retrieval/evidence refs
- runtime policy refs
- data classification/scope metadata where available
- context hash

Raw cross-service databases are not joined into AE context.

---

## P5-DEC-05 — Deterministic plan profiles are mandatory before LLM dynamic planning

P5 SHALL first support deterministic/template-bound plans for known v1 execution modes.

Example:

```text
GENERAL_ANSWER
→ one-step/direct generation profile

GROUNDED_ANSWER
→ retrieval → generation/report profile

DOCUMENT_SUMMARY
→ retrieval/context → summary/report profile

DOCUMENT_GENERATION
→ retrieval/context → generation → artifact/report profile
```

Exact capability IDs and executable kinds SHALL be derived from Frozen Agent design/current service boundaries rather than invented as external API vocabulary.

LLM dynamic Plan Builder is optional in P5 and, if added, MUST pass the same validator/compiler.

---

## P5-DEC-06 — AgentPlan is never directly executable

All AgentPlan instances SHALL pass:

```text
Plan Validator
→ Deterministic Compiler
```

before any step is runnable.

No model-generated PlanStep may directly call CX/MO/NSL/WC/provider endpoints.

---

## P5-DEC-07 — Multi-step runtime reuses P4 AgentExecution/RuntimeJob/ExecutableStep

P5 SHALL extend P4 structures.

It SHALL NOT create a second execution/job/step hierarchy.

P5 MAY alter/add columns and constraints to support:

- executable_plan_id
- logical plan step identity
- step order
- dependencies
- executor kind
- input/output bindings
- step result identity

P4 compatibility rows remain readable.

---

## P5-DEC-08 — P5 supports a bounded executor set; LOCAL_SKILL is schema-visible but unavailable

P5 SHALL implement the executor semantics needed for current Chat/RAG planning, such as:

- compatibility/direct execution
- retrieval/context acquisition
- model/generation
- deterministic aggregation where needed
- report/result projection

Exact names SHALL follow Frozen Agent Doc 05/06 if defined.

P5 SHALL retain `LOCAL_SKILL` / NSL-bound capability in the Frozen contract
vocabulary and executor-registration seam. A P5 plan that requires it SHALL
fail validation or compilation with `EXECUTOR_NOT_AVAILABLE` before an
ExecutablePlan or READY step is materialized. P5 does not create a synthetic
StepResult for work that was never executable.

---

## P5-DEC-09 — DELEGATE_WORK is not executed in P5

Logical delegation belongs to WC / background Agent phases.

P5 validator/compiler SHALL reject or mark unsupported any Plan that requires DELEGATE_WORK.

No WC WorkItem is created in P5.

---

## P5-DEC-10 — Multi-step execution is deterministic and crash-safe

P5 SHALL use durable RuntimeJobs and persisted step state/results.

A process restart MUST NOT cause a succeeded step to execute again.

Step scheduling SHALL be based on persisted dependency/result state, not in-memory recursion.

---

## P5-DEC-11 — Initial execution ordering is deterministic serial-ready order

P5 MAY represent a DAG but SHALL execute one ready step at a time in deterministic order for the first closure.

Parallel step execution is deferred unless Frozen semantics make it mandatory.

This reduces concurrency risk before P6/P7.

---

## P5-DEC-12 — AgentResult is created only after plan completion/terminalization

P4 created AgentResult after one compatibility step.

P5 SHALL move final result assembly to plan-level completion:

```text
all required steps terminal
→ verify completion criteria
→ aggregate StepResults
→ AgentResult
```

Intermediate StepResult MUST NOT create a final AgentResult.

P4 pending ResultDelivery behavior remains unchanged.

---

## P5-DEC-13 — Clarification is fail-safe

If intent/entity/parameter resolution requires clarification:

```text
AgentExecution.state = WAITING_INPUT
phase = INTENT_RESOLUTION or CONTEXT_EXPANSION
```

P5 MUST NOT invent missing authoritative values.

P5 persists and exposes the waiting record and user-facing clarification, but
clarification resume is explicitly deferred by P5-DEC-20.

---

## P5-DEC-14 — P5 ends before NSL

P5 proves planning and multi-step execution with existing AE/CX/MO capabilities.

P5 SHALL NOT:

- resolve NSP
- verify Skill package
- create NSLExecutionId
- call NSL Runtime
- derive NSL IdempotencyKey
- execute WRITE

---

## P5-DEC-15 — CA01 transition contracts are implementation normative

Frozen semantic authority remains unchanged. For P5 implementation, the exact
machine shapes under `docs/transition/P5/contracts/` are normative over the
legacy `99_*` reference schemas.

Frozen plan kinds:

```text
DIRECT | CERTIFIED_BINDING | KNOWN_TEMPLATE | DYNAMIC
```

Frozen logical step types:

```text
LOCAL_CAPABILITY | DELEGATE_WORK | AGGREGATE | REPORT
```

P5 exposes the full logical vocabulary but scope guards reject
`DELEGATE_WORK`. P5 active executable types are `CANONICAL_CAPABILITY`,
`AGGREGATE`, and `REPORT`.

---

## P5-DEC-16 — Project-neutral intent is not incomplete by default

An IA `PROMPT` with `project_id=null` is valid unless its selected capability,
entity selector, or completion criteria requires an authoritative Project.

P5 SHALL NOT create `COMMON_PROJECT`, a personal default Project, or any other
synthetic Project to satisfy planning.

---

## P5-DEC-17 — Capability snapshots are tenant-scoped and exact

P5 SHALL persist tenant-scoped immutable capability snapshots. Every AgentPlan
binds an exact snapshot ID/version/hash and no planning, validation, retry, or
restart path resolves an implicit latest snapshot.

Initial internal capabilities are:

```text
AE.CHAT.COMPATIBILITY
AE.RESULT.REPORT
```

They are internal transition vocabulary and are not public API identifiers.

---

## P5-DEC-18 — P5 hash and revision semantics are uniform

All P5 semantic envelope hashes use the canonical JSON/SHA-256 profile defined
by P5-CA01 DEC-11 and are stored as `sha256:<64 lowercase hex>`.

WorkIntent, AgentContext, AgentPlan, PlanValidationResult, ExecutablePlan, and
StepResult are insert-only semantic records. A changed semantic object receives
a new identity/version/generation and explicit lineage instead of mutating prior
evidence.

---

## P5-DEC-19 — Prompt Registry is mandatory only at enabled LLM boundaries

The existing AE RDBMS Prompt Registry is the sole P5 prompt authority.
Deterministic intent and plan stages do not resolve unused prompt purposes.
Every LLM-dependent stage enabled by the selected P5 mode SHALL:

- resolve an exact explicit binding;
- use an immutable template version;
- record content/render/model/output provenance;
- fail closed in required mode when the binding or hash is invalid.

Prompt template versions use insert-or-verify semantics. Binding changes are
explicit mutable pointers with durable history. Optional LLM intent and dynamic
planning remain disabled by default and are not required for P5 closure.

---

## P5-DEC-20 — Clarification resume is deferred, not implied

P5 SHALL persist explicit questions and `WAITING_INPUT` with zero executable
steps and zero provider/business side effects. P5 does not add
`RESUME_EXECUTION`; P4's `START_EXECUTION | CONTINUE_EXECUTION` job vocabulary
remains unchanged.

Later resume support must be a controlled change that creates a new immutable
WorkIntent revision and deduplicates the answer event. It must not update the
waiting WorkIntent in place.
