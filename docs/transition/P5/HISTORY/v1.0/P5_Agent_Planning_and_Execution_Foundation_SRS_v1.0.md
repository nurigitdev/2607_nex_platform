# P5 — NeX Agent Planning & Execution Foundation SRS v1.0

**Document Status:** P5-CA01 REVIEWED IMPLEMENTATION BASELINE

**Target:** branch created from completed P4 implementation baseline

**Predecessor:** P4 Canonical Agent Runtime Foundation

**Successor:** P6 NSL v0.2 READ Integration
**Frozen Authority:** `docs/frozen/v2.1/`

---

# 1. Purpose

P5 implements the missing planning layer between natural-language user input and the canonical Agent Runtime established by P4.

P5 SHALL transform:

```text
Natural-language Prompt
```

into:

```text
WorkIntent
→ AgentContext
→ AgentPlan
→ validated AgentPlan
→ deterministic ExecutablePlan
→ ordered/durable ExecutableStep execution
→ StepResult[]
→ AgentResult
```

P5 SHALL prove that a single AgentExecution can execute more than one durable step.

P5 SHALL NOT invoke NSL. NSL READ integration begins in P6.

---

# 2. P4 As-Built Starting Point

P5 starts from the actual P4 implementation, including:

```text
services/nex-ae-api/nex_ae_api/
  agent_execution.py
  agent_identity.py
  agent_results.py
  agent_runtime_foundation.py
  chat_application.py
  conversation_journal.py
  executable_steps.py
  runtime_jobs.py
  intent_policy.py
  runtime_policy.py
```

and P4 migrations:

```text
2001_ae_agent_identity.sql
2002_ae_conversation_journal.sql
2003_ae_agent_execution.sql
2004_ae_runtime_job.sql
2005_ae_executable_step.sql
2006_ae_agent_result.sql
```

P4 already provides:

- canonical `AgentExecution`
- Frozen AgentExecution state/phase vocabulary
- canonical RuntimeJob/Attempt foundation
- one P4 compatibility ExecutableStep
- Chat/RAG application-service boundary
- AgentResult
- PENDING required WORKSPACE_RESULT ResultDelivery
- project-neutral IA PROMPT admission
- correlation/trace foundation

P5 SHALL extend these objects rather than create parallel identities.

---

# 3. Relevant Frozen Agent Stages

P5 covers the following Frozen Agent execution phases:

```text
BASE_CONTEXT
INTENT_RESOLUTION
CONTEXT_EXPANSION
PLAN_BUILD
PLAN_VALIDATE
PLAN_COMPILE
STEP_EXECUTION
RESULT_VERIFY
RESULT_SYNTHESIS
```

`RESULT_PUBLISH` remains subject to the P4 publication boundary.

---

# 4. Authority / Contract Rule

Frozen Agent DOCX documents 02–06 are the semantic authority for:

- intent resolution
- context construction
- plan construction
- plan validation
- deterministic compilation
- step execution

The JSON contracts under `04_LEGACY_REFERENCE_CONTRACTS` are reference-only seeds.

P5 MAY derive transition contracts from them, but SHALL record any divergence.

P5 MUST NOT silently declare a legacy reference schema to be Frozen normative.

P5-CA01 completed the required extraction. The implementation-facing transition
schemas under `docs/transition/P5/contracts/` are normative for P5 where legacy
reference schemas differ. The Frozen source files remain unchanged.

---

# 5. P5 Goals

## P5-GOAL-01 — Structured WorkIntent

Produce a durable structured WorkIntent from the authenticated prompt and P4 execution context.

## P5-GOAL-02 — AgentContext Snapshot

Build a bounded, immutable/versioned AgentContext containing only authoritative/resolved references and bounded context metadata.

## P5-GOAL-03 — AgentPlan

Produce an immutable logical AgentPlan.

At least deterministic/template-bound planning SHALL be production-capable in P5.

## P5-GOAL-04 — Plan Validation

Reject structurally or semantically unsafe plans before execution.

## P5-GOAL-05 — Deterministic Compilation

Compile a validated AgentPlan into an immutable ExecutablePlan and durable ExecutableSteps.

## P5-GOAL-06 — Multi-Step Runtime

Execute at least one acceptance flow containing two or more durable steps.

## P5-GOAL-07 — StepResult Foundation

Persist immutable StepResult records so later steps and P6 NSL integration consume results by reference.

## P5-GOAL-08 — Plan-Level Result Finalization

Create AgentResult only after required plan steps have terminalized and completion criteria have been evaluated.

## P5-GOAL-09 — P6-Ready LOCAL_SKILL Seam

Provide a deterministic compiler/executor registration seam for a future NSL-backed `LOCAL_SKILL` execution kind without calling NSL in P5.

---

# 6. Explicit In Scope

- WorkIntent transition contract/persistence
- deterministic v1 IntentDecision → WorkIntent adapter
- optional LLM IntentCandidate interface, disabled/shadow by default
- clarification decision and WAITING_INPUT boundary
- AgentContext snapshots and hashes
- trusted entity/context resolver interface
- planning capability catalog snapshot
- deterministic/template Plan Builder
- optional LLM Plan Builder interface, not required for closure
- AgentPlan persistence/hash/version
- Plan Validator
- deterministic compiler
- ExecutablePlan persistence/hash
- generalization of P4 `ae_executable_step`
- StepResult persistence
- dependency-aware deterministic step scheduler
- START/CONTINUE RuntimeJob integration
- existing P4 Chat/RAG step as a supported executor
- deterministic report/aggregation executor sufficient for multi-step closure
- AgentResult assembly from StepResults
- P4 compatibility/regression preservation

---

# 7. Explicit Out of Scope

P5 MUST NOT implement:

- NSP resolution
- Skill Artifact Gateway
- VerifiedSkillArtifact
- NSLExecutionId
- NSL Runtime calls
- NSL READ execution
- NSL WRITE
- WRITE approval
- BusinessOperationId WRITE semantics
- WC WorkItem / Claim
- CA / PA / EA background execution
- DELEGATE_WORK execution
- Enterprise OS WRITE
- WA
- Schedule / recurring work
- full ResultDelivery publication ACK
- production multi-step parallel execution
- unrestricted autonomous replanning loops

---

# 8. P5 Identity Model

P5 introduces:

```text
WorkIntentId
AgentContextId / ContextVersion
AgentPlanId / PlanVersion
PlanValidationId
ExecutablePlanId
LogicalPlanStepId
StepResultId
CapabilityCatalogSnapshotId
```

Existing identities remain distinct:

```text
AgentExecutionId
RuntimeJobId
ExecutableStepId
AgentResultId
InteractionId
CX GenerationId
CX JobId
GeneratedResponseId
```

Mandatory:

```text
WorkIntentId      != AgentExecutionId
AgentPlanId       != ExecutablePlanId
LogicalPlanStepId != ExecutableStepId
StepResultId      != AgentResultId
```

---

# 9. WorkIntent Requirements

## P5-INT-001

WorkIntent SHALL be an immutable structured output of intent resolution.

## P5-INT-002

WorkIntent SHALL reference:

- tenant_id
- agent_execution_id
- trigger/source reference
- goal
- work class/category
- execution-mode/profile hint
- capability hints
- entity selectors
- parameter candidates
- constraints
- completion criteria
- clarification status
- confidence/provenance
- intent hash

## P5-INT-003

Unresolved entities SHALL be represented as selectors/candidates, not authoritative IDs.

## P5-INT-004

A model/heuristic MUST NOT assign a stable Project/business-object ID unless a trusted resolver confirms it.

## P5-INT-005

The existing `intent_policy.py` SHALL be reused as the first mandatory resolver adapter for:

```text
GENERAL_ANSWER
GROUNDED_ANSWER
DOCUMENT_SUMMARY
DOCUMENT_GENERATION
```

## P5-INT-006

P5 SHOULD preserve the existing explicit execution-mode override behavior.

## P5-INT-007

WorkIntent persistence SHALL store the full safe envelope plus a deterministic semantic hash.

Raw prompt content SHOULD remain referenced via Conversation/Interaction storage rather than duplicated.

## P5-INT-008

If clarification is required because of ambiguous/missing required information, planning SHALL NOT continue as if resolved.

---

# 10. Clarification / WAITING_INPUT

## P5-WAIT-001

P5 SHALL support a deterministic clarification outcome from Intent/Context processing.

## P5-WAIT-002

When clarification is required:

```text
AgentExecution.state = WAITING_INPUT
phase = INTENT_RESOLUTION or CONTEXT_EXPANSION
```

## P5-WAIT-003

The system SHALL persist:

- clarification reason codes
- user-safe questions
- unresolved selector refs
- source WorkIntent/Context refs

## P5-WAIT-004

No missing Project/entity/value may be fabricated to avoid WAITING_INPUT.

## P5-WAIT-005

A generic Wait/Resume framework and clarification resume are not implemented in
P5. P5 SHALL persist the clarification request and stop with zero executable
steps and zero provider/business side effects.

P5 SHALL NOT add `RESUME_EXECUTION` to the P4 RuntimeJob vocabulary. A later
controlled change may implement resume by creating a new immutable WorkIntent
revision on the same AgentExecution; it must not mutate the waiting WorkIntent.

---

# 11. AgentContext Requirements

## P5-CTX-001

AgentContext SHALL be a bounded snapshot, not a cross-service data dump.

## P5-CTX-002

AgentContext SHALL include references/snapshots for applicable:

- authenticated Principal
- IA AgentIdentity
- tenant
- workspace
- conversation
- project/business refs only when authoritative
- selected documents/resources
- runtime policy
- retrieval/evidence refs when already known
- classification/scope metadata when available
- context provenance
- context hash

## P5-CTX-003

AgentContext SHALL NOT contain raw credentials or provider secrets.

## P5-CTX-004

Cross-service data SHALL be represented by stable reference/evidence contracts, not database joins.

## P5-CTX-005

Context expansion SHALL create a new immutable/versioned context snapshot rather than silently mutating historical planning input.

## P5-CTX-006

Same effective context inputs SHALL produce the same context semantic hash.

## P5-CTX-007

Whole AgentContext SHALL NOT be designed as a future NSL runtime_context payload.

P6 will perform deterministic typed projection.

---

# 12. Capability Catalog Requirements

## P5-CAP-001

P5 SHALL introduce a versioned planning/execution capability catalog or equivalent immutable snapshot.

## P5-CAP-002

Each capability descriptor SHALL minimally identify:

- capability_id
- exact version or versioned contract
- logical purpose
- executor kind
- input contract/schema ref
- output contract/schema ref
- availability/enabled state
- risk/side-effect classification sufficient to block unsupported WRITE
- owning service/component
- deterministic descriptor hash

## P5-CAP-003

Plan provenance SHALL bind to a capability-catalog snapshot/hash.

The P5 snapshot SHALL be tenant-scoped and immutable.

## P5-CAP-004

No `latest` version substitution is allowed during deterministic compile.

## P5-CAP-005

P5 SHALL register only capabilities P5 can safely execute.

A future NSL/LOCAL_SKILL capability type MAY exist in contract vocabulary, but SHALL not be runnable until P6.

## P5-CAP-006

Capability IDs chosen in P5 SHALL be reviewed against Frozen Agent terminology before being exposed as stable external API vocabulary.

Initial internal IDs are `AE.CHAT.COMPATIBILITY` and `AE.RESULT.REPORT`. They
are not public external API vocabulary.

---

# 12A. Prompt Registry Requirements

## P5-PRM-001

The existing AE RDBMS Prompt Registry SHALL be the only P5 runtime prompt
authority.

## P5-PRM-002

Every LLM-dependent stage enabled by the selected P5 runtime mode SHALL resolve
an explicit binding and exact immutable template version. Deterministic stages
SHALL NOT resolve unused prompt purposes.

## P5-PRM-003

Prompt template versions SHALL use insert-or-verify semantics. Same-key
same-content writes are idempotent; same-key changed-content writes fail closed.

## P5-PRM-004

Binding changes SHALL retain durable activation/rollback history without
mutating template version content.

## P5-PRM-005

Enabled LLM execution provenance SHALL include binding key, template version
ID, content hash, rendered prompt hash, model profile/ref, and output hash.

Optional LLM Intent Resolution and Dynamic Plan Builder remain disabled by
default and are not required for P5 closure.

---

# 13. AgentPlan Requirements

## P5-PLAN-001

AgentPlan SHALL be immutable after creation.

## P5-PLAN-002

AgentPlan SHALL reference:

- agent_execution_id
- work_intent_id
- context_ref/hash
- plan_id
- plan_version
- plan kind
- goal
- completion criteria
- ordered logical steps
- planner provenance
- capability-catalog snapshot ref/hash
- plan hash

## P5-PLAN-002A

P5 SHALL use Frozen plan kinds:

```text
DIRECT | CERTIFIED_BINDING | KNOWN_TEMPLATE | DYNAMIC
```

P5 deterministic profiles use `DIRECT` and `KNOWN_TEMPLATE`. The maximum plan
size is 12 logical steps, effective delegation depth is 0, and runtime parallel
step count is 1.

## P5-PLAN-003

P5 SHALL support deterministic/template-bound plans for the current four execution modes.

## P5-PLAN-004

A deterministic one-step or compatibility plan MAY be used for existing behavior.

## P5-PLAN-005

At least one acceptance flow SHALL produce an AgentPlan with two or more logical steps.

## P5-PLAN-006

If an LLM Plan Builder is added, its output is only a candidate AgentPlan.

It receives no direct authority to execute.

## P5-PLAN-007

Planner rationale, if persisted/presented, SHALL be a short user-safe rationale summary, not private chain-of-thought.

## P5-PLAN-008

Plan versions SHALL be explicit.

Replan, if implemented, SHALL create a new version / superseding plan, not mutate the prior plan.

Unbounded automatic replanning is out of scope.

---

# 14. P5 Minimum Planning Profiles

P5 SHALL define deterministic planning profiles for existing v1 behavior.

The exact capability IDs/executor-kind names SHALL be fixed by the P5 Source Audit after Frozen Doc 04–06 extraction.

The minimum semantics are:

## P5-PROFILE-01 — General Answer

```text
Intent: GENERAL_ANSWER
Plan: direct/compatibility answer execution
Result: interactive response
```

## P5-PROFILE-02 — Grounded Answer

At minimum:

```text
context/evidence capable execution
→ answer/report projection
```

P5 SHOULD separate retrieval and final response steps if the source refactor is safe.

If not, it MAY use the existing P4 Chat/RAG compatibility executor plus a separate deterministic report/result step.

## P5-PROFILE-03 — Document Summary

At minimum:

```text
document-grounded compatibility/local capability
→ summary/report result
```

## P5-PROFILE-04 — Document Generation

At minimum:

```text
document-grounded compatibility/local capability
→ artifact/report result
```

No profile may call NSL in P5.

---

# 15. Plan Validator Requirements

## P5-VAL-001

Plan validation SHALL be deterministic.

## P5-VAL-002

Validator SHALL reject:

- missing required plan identity
- execution/work-intent/context mismatch
- duplicate logical step IDs
- dependency on missing step
- dependency cycle
- self-dependency
- invalid input binding
- output binding to nonexistent step
- unsupported capability
- disabled capability
- implicit latest version
- unsupported executor
- unsupported DELEGATE_WORK in P5
- unsupported WRITE/approval semantics
- plan size/resource bounds exceeded

## P5-VAL-003

P5 SHALL use a bounded maximum step count.

P5 SHALL enforce a maximum of `12` logical steps, as fixed by the CA01
transition contract extraction. This is the bounded first-closure profile and
does not widen the Frozen product contract.

## P5-VAL-004

Validator output SHALL be a durable validation record:

```text
status =
  VALID |
  REPLAN_REQUIRED |
  CONTEXT_REFRESH_REQUIRED |
  CLARIFICATION_REQUIRED |
  BLOCKED |
  INVALID_TERMINAL |
  RETRYABLE_VALIDATION_FAILURE
agent_plan_ref
validated_context_ref
issues[]
topological_step_order[]
validator_version
validated_at
result_hash
```

The exact envelope is `contracts/p5-plan-validation-result-v1.schema.json`.
Plan and capability-snapshot identity/hash are retained through the immutable
AgentPlan reference; implementations SHALL NOT replace the Frozen status
vocabulary with a lossy `PASS/FAIL` field.

## P5-VAL-005

A failed validation MUST result in zero ExecutablePlan/Step execution.

---

# 16. Deterministic Compiler Requirements

## P5-CMP-001

Only a validated AgentPlan may be compiled.

## P5-CMP-002

Compiler inputs SHALL bind:

- exact AgentPlan hash/version
- WorkIntent ref/hash
- AgentContext ref/hash
- CapabilityCatalog snapshot/hash
- compiler version

## P5-CMP-003

Compiler SHALL create an immutable ExecutablePlan.

## P5-CMP-004

Compiler SHALL create stable logical-to-executable mappings:

```text
LogicalPlanStepId → ExecutableStepId
```

## P5-CMP-005

Compiler SHALL resolve exact executor/capability versions.

## P5-CMP-006

Compilation SHALL be deterministic for identical semantic inputs and catalog snapshot.

## P5-CMP-007

Compiler SHALL produce a deterministic executable-plan hash.

## P5-CMP-008

Compiler MUST NOT invoke a provider/model/tool/NSL while compiling.

## P5-CMP-009

A plan requiring an NSL/LOCAL_SKILL executor before P6 SHALL fail closed as unavailable/unsupported for execution.

The compiler/executor seam SHALL remain P6-compatible.

---

# 17. ExecutablePlan Requirements

## P5-EPL-001

ExecutablePlan SHALL be immutable.

## P5-EPL-002

It SHALL include:

- executable_plan_id
- agent_execution_id
- agent_plan_id/version/hash
- context ref/hash
- capability snapshot ref/hash
- compiler version
- compiled step refs/order
- executable plan hash
- created_at

## P5-EPL-003

AgentExecution SHALL reference the active ExecutablePlan.

## P5-EPL-004

Historical plans SHALL remain traceable if a later replan is introduced.

---

# 18. ExecutableStep Generalization

P4 migration `2005_ae_executable_step.sql` currently restricts:

```text
step_kind = P4_CHAT_RAG_COMPATIBILITY
```

and enforces one row per `(tenant, execution, step_kind)`.

P5 SHALL generalize this table.

## P5-STEP-001

P5 SHALL preserve existing P4 compatibility rows.

## P5-STEP-002

New P5 rows SHALL support:

- executable_plan_id
- logical_step_id
- deterministic step index/order
- executor kind
- required capability/version
- dependencies
- input bindings
- expected output contract
- state/version
- result_ref
- correlation/causation

## P5-STEP-003

P5 SHALL remove/replace the P4-only uniqueness rule that prevents multiple steps.

## P5-STEP-004

New uniqueness SHALL prevent duplicate logical-step materialization within the same ExecutablePlan.

## P5-STEP-005

The exact step/executor vocabulary SHALL follow Frozen Agent Doc 05/06 if defined.

If implementation-specific executor labels are necessary, they SHALL be explicitly documented as P5 internal vocabulary.

---

# 19. StepResult Requirements

## P5-SR-001

Every terminal executable step SHALL produce or reference one immutable StepResult.

## P5-SR-002

StepResult SHALL minimally bind:

- tenant_id
- step_result_id
- agent_execution_id
- executable_plan_id
- executable_step_id
- logical_step_id
- status
- structured result/ref
- artifact/evidence refs
- warnings/error ref
- input-result-set hash
- result hash
- created_at

## P5-SR-003

StepResult SHALL not duplicate raw large/private content when stable refs exist.

## P5-SR-004

Later steps SHALL consume prior step output through StepResult references/bindings, not mutable in-memory objects only.

## P5-SR-005

P6 SHALL be able to map an NSLResultSummary into the same StepResult contract.

---

# 20. Step Execution Engine Requirements

## P5-ENG-001

The Step Execution Engine SHALL schedule from persisted ExecutablePlan/Step/StepResult state.

## P5-ENG-002

A process restart SHALL not re-execute a terminal succeeded step.

## P5-ENG-003

A step becomes runnable only when all required dependencies have acceptable terminal results.

## P5-ENG-004

P5 SHALL use deterministic ready-step selection.

Initial closure MAY execute serially by:

```text
step_index, logical_step_id
```

or exact Frozen deterministic order.

## P5-ENG-005

Each step execution SHALL be driven by a canonical RuntimeJob.

P5 MAY use `CONTINUE_EXECUTION` for step progression.

## P5-ENG-006

RuntimeJob payload SHALL carry references, not raw prompt/result bodies.

## P5-ENG-007

Technical retry of a step remains within the same:

```text
AgentExecution
ExecutablePlan
ExecutableStep
```

unless a real replan is explicitly created.

## P5-ENG-008

The engine SHALL fail closed for an unavailable executor.

## P5-ENG-009

`DELEGATE_WORK` SHALL not create WorkItem in P5.

## P5-ENG-010

`LOCAL_SKILL`/NSL-bound execution SHALL not call NSL in P5.

---

# 21. P5 Executor Requirements

P5 closure requires at least:

## P5-EXEC-01 — P4 Compatibility Executor

Reuse the existing P4 Chat/RAG compatibility application service/runtime path.

It SHALL preserve:

- retrieval/generation idempotency
- async continuation
- GeneratedResponse integrity
- artifact behavior

## P5-EXEC-02 — Deterministic Report/Aggregation Executor

Provide a local deterministic executor capable of consuming prior StepResult refs and producing a bounded final/report StepResult.

This executor exists to prove true multi-step plan execution without introducing NSL.

## P5-EXEC-03 — Optional Explicit Retrieval/Model Executors

P5 MAY split retrieval and model generation into separate executors if source refactoring is safe and regression remains green.

This is not required for P5 closure.

---

# 22. AgentExecution Phase Transitions

P5 SHALL drive real planning phases.

Minimum transition sequence for a successful planned execution:

```text
INTAKE / BASE_CONTEXT
→ INTENT_RESOLUTION
→ CONTEXT_EXPANSION
→ PLAN_BUILD
→ PLAN_VALIDATE
→ PLAN_COMPILE
→ STEP_EXECUTION
→ RESULT_VERIFY
→ RESULT_SYNTHESIS
→ RESULT_PUBLISH
```

State remains according to Frozen semantics, normally RUNNING except explicit wait/block/failure states.

P5 MUST NOT transition to `SUCCEEDED` while P4 required ResultDelivery remains PENDING.

---

# 23. AgentResult Finalization

## P5-RES-001

Intermediate successful StepResult MUST NOT create AgentResult.

## P5-RES-002

AgentResult may be created only when all required plan completion conditions are satisfied or the plan terminalizes into a defined blocked/failed/cancelled outcome.

## P5-RES-003

AgentResult provenance SHALL reference:

- WorkIntent
- AgentContext
- AgentPlan
- PlanValidation
- ExecutablePlan
- StepResults
- P4/CX/GeneratedResponse refs where applicable

## P5-RES-004

Existing P4 result hash and pending ResultDelivery rules remain authoritative until later publication phase.

---

# 24. Persistence Requirements

P5 SHOULD use additive migrations beginning after P4 `2006`.

Recommended profile:

```text
2101_ae_work_intent.sql
2102_ae_agent_context.sql
2103_ae_agent_plan.sql
2104_ae_executable_plan.sql
2105_ae_executable_step_planning.sql
2106_ae_step_result.sql
```

Exact numbering may follow repository conventions.

## P5-PER-001

Existing P4 rows SHALL remain readable.

## P5-PER-002

P5 SHALL not destructively rename P4 identities.

## P5-PER-003

Any `ae_executable_step` constraint widening SHALL preserve historical compatibility rows.

## P5-PER-004

Cross-service foreign keys remain prohibited.

## P5-PER-005

PostgreSQL remains canonical; SQLite may provide behaviorally equivalent fast regression.

---

# 25. Proposed Physical Persistence Profiles

## 25.1 WorkIntent

```text
tenant_id
work_intent_id
agent_execution_id
schema_version
intent_revision
supersedes_work_intent_id
envelope_json
intent_hash
created_at
```

Unique `(tenant, execution, intent_revision)` prevents divergent WorkIntent for
the same revision. Changed intent creates a new immutable revision.

## 25.2 AgentContext

```text
tenant_id
agent_context_id
agent_execution_id
work_intent_id
context_generation
context_json
context_hash
created_at
```

Unique `(tenant, execution, context_generation)`.

## 25.3 Capability Catalog Snapshot

```text
tenant_id
capability_snapshot_id
snapshot_version
capabilities_json
snapshot_hash
created_at
```

P5 uses tenant-scoped immutable snapshots. Platform-global deduplication is
outside P5.

## 25.4 AgentPlan

```text
tenant_id
agent_plan_id
agent_execution_id
work_intent_id
agent_context_id
plan_version
plan_kind
plan_json
plan_hash
capability_snapshot_id
created_at
```

## 25.5 PlanValidation

```text
validation_id
tenant_id
agent_plan_id
status
validation_result_json
result_hash
validator_version
created_at
```

The physical row may project indexed columns from the envelope, but
`validation_result_json` remains conformant to the CA01 validation schema.

## 25.6 ExecutablePlan

```text
tenant_id
executable_plan_id
agent_execution_id
agent_plan_id
agent_context_id
compiler_version
executable_plan_json
executable_plan_hash
created_at
```

## 25.7 StepResult

```text
tenant_id
step_result_id
agent_execution_id
executable_plan_id
executable_step_id
logical_step_id
status
result_json
result_hash
created_at
```

---

# 26. Compatibility Requirements

## P5-COMP-001

`NEX_AE_AGENT_RUNTIME_MODE=disabled` SHALL preserve P4/v1 behavior.

## P5-COMP-002

P5 planning feature SHALL have its own controlled rollout mode or sub-mode.

Recommended:

```text
NEX_AE_PLANNING_MODE=disabled|shadow|required
```

## P5-COMP-003

In shadow mode:

- WorkIntent/Context/Plan MAY be generated and validated
- legacy P4 compatibility execution remains response-authoritative
- planning failure cannot break a valid legacy response
- shadow plan MUST NOT execute additional external side effects

## P5-COMP-004

In required mode:

- valid WorkIntent
- valid AgentContext
- Plan validation status is `VALID`
- deterministic compile
- ExecutablePlan persistence

are mandatory before step execution.

---

# 27. Security / Safety Requirements

## P5-SEC-001

LLM/heuristic output is never authority for:

- tenant
- principal
- role
- project ID
- business object ID
- provider endpoint
- skill/package version
- approval
- WRITE authorization

## P5-SEC-002

Resolved entity refs SHALL carry provenance/source.

## P5-SEC-003

Plan input bindings SHALL not bypass owner/scope enforcement.

## P5-SEC-004

P5 capability catalog SHALL not expose raw provider endpoints/secrets.

## P5-SEC-005

No execution path may invoke an unregistered/unvalidated capability.

---

# 28. Observability Requirements

Trace SHALL be extendable to:

```text
AgentExecutionId
→ WorkIntentId
→ AgentContextId
→ AgentPlanId
→ PlanValidationId
→ ExecutablePlanId
→ ExecutableStepId[]
→ StepResultId[]
→ AgentResultId
```

Observability SHALL expose hashes/refs/statuses, not raw private prompt/context/result content.

---

# 29. Required Test Classes

## 29.1 Intent

- explicit mode
- deterministic existing rules
- retrieval-requested promotion
- ambiguous/unresolved entity
- missing required parameter
- no fabricated authoritative ID
- stable intent hash

## 29.2 Context

- base context
- versioned expansion
- owner isolation
- unresolved selector
- stable context hash
- no credential/raw provider leak

## 29.3 Plan

- known deterministic profiles
- plan hash repeatability
- duplicate step ID
- missing dependency
- cycle
- unsupported DELEGATE_WORK
- unsupported WRITE
- unregistered capability
- plan step bound

## 29.4 Compiler

- same inputs → same executable plan hash
- exact capability version binding
- no latest substitution
- unavailable LOCAL_SKILL rejected before P6
- no external call during compile

## 29.5 Execution Engine

- multi-step serial success
- dependency blocking
- restart after step success
- no duplicate step execution
- technical retry same step
- failed step stops dependent execution
- StepResult persistence
- compatibility executor called once
- async continuation not replayed

## 29.6 Result

- no AgentResult after intermediate step
- final AgentResult contains plan/step provenance
- blocked/failed mapping
- existing PENDING ResultDelivery rule preserved
- no SUCCEEDED without ACK

---

# 30. P5 Acceptance Scenarios

## P5-AC-01 — General Answer Planning

```text
PROMPT
→ WorkIntent
→ AgentContext
→ validated deterministic Plan
→ ExecutablePlan
→ step execution
→ AgentResult
```

Existing user-visible behavior remains compatible.

## P5-AC-02 — Multi-Step Grounded/Document Scenario

At least two persisted ExecutableSteps execute in dependency order.

The acceptance flow SHALL prove StepResult handoff between steps.

The flow MAY use:

```text
P4 Chat/RAG compatibility executor
→ deterministic report/result executor
```

if explicit retrieval/model split is not yet safe.

## P5-AC-03 — Clarification

Ambiguous required entity/parameter produces:

```text
WAITING_INPUT
```

with zero plan execution side effects.

## P5-AC-04 — Invalid Plan

Cyclic/missing-dependency/unsupported plan:

```text
status is not `VALID`
→ no ExecutablePlan execution
```

## P5-AC-05 — NSL Boundary

A plan requiring an NSL/LOCAL_SKILL-only capability is not executed.

No NSL network/process invocation occurs.

## P5-AC-06 — P4 Regression

P4 canonical runtime and existing Chat/RAG tests remain PASS.

---

# 31. Quality Gates

Follow repository Slice/Checkpoint/Full Gate discipline.

Minimum changed-source targets:

```text
statement coverage >= 95%
branch coverage    >= 94%
```

Protected PostgreSQL smoke SHALL prove:

- migrations
- immutable WorkIntent/Context/Plan
- deterministic hashes
- multi-step materialization
- restart-safe scheduling
- no duplicate StepResult
- cleanup/zero residue

Relevant Playwright Chat/RAG regression remains mandatory.

---

# 32. P5 Exit Gate

P5 closes only when:

```text
Natural-language Prompt
→ canonical WorkIntent
→ canonical AgentContext
→ AgentPlan
→ deterministic validation status=VALID
→ deterministic ExecutablePlan
→ multiple durable ExecutableSteps
→ durable StepResults
→ AgentResult
```

is traceable in one AgentExecution,

AND:

- existing P4 behavior/regression remains PASS
- invalid plans cannot execute
- unresolved entities do not become fake IDs
- P5 does not call NSL
- P5 does not create WC work
- AgentExecution is not falsely marked SUCCEEDED while ResultDelivery is PENDING

---

# 33. P6 Handoff Contract

P5 SHALL finish with a stable extension seam:

```text
Logical LOCAL_CAPABILITY
→ deterministic capability resolution
→ ExecutableStep executor binding
```

P6 will extend that seam:

```text
executor_kind = LOCAL_SKILL
→ Skill Artifact Gateway
→ VerifiedSkillArtifact
→ SkillExecutionRequest
→ NSL v0.2 READ
→ NSLResultSummary
→ StepResult
```

P6 MUST NOT need to rename:

- AgentExecutionId
- WorkIntentId
- AgentContextId
- AgentPlanId
- ExecutablePlanId
- ExecutableStepId
- StepResultId
