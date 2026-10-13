# P5 Source Audit and Implementation Plan v1.0

**Status:** P5-CA01 REVIEWED IMPLEMENTATION BASELINE

**Phase:** P5 Agent Planning & Execution Foundation
**Implementation state:** NOT STARTED

---

## 1. Mandatory First Action

Before modifying code, Codex SHALL:

1. read `docs/frozen/v2.1/README_FROZEN_BASELINE.md`;
2. extract/read Frozen Agent Docs 01–06, 08, 10, 99;
3. read current `docs/transition/P4/` v1.1 closure documents;
4. inspect current P4 source and DB migrations;
5. compare Frozen semantics with reference schemas:
   - `99_work-intent-v1.schema.json`
   - `99_agent-plan-v1.schema.json`
   - `99_plan-step-v1.schema.json`;
6. update the P5 Issue Register with any semantic conflict;
7. produce exact P5 transition contract shapes before feature coding.

No source feature work should begin before this audit is reviewed.

### P5-CA01 Completion Record

P5-CA01 completed the mandatory actions above on 2026-10-13. The reviewed
source hashes are recorded in `P5_CA01_Frozen_Source_Manifest_v1.0.csv`, and the
exact transition shapes are under `contracts/`.

The design entry gate is closed. This statement does not claim that any P5
feature, migration, or runtime path has been implemented.

---

## 2. Current P4 Source Facts to Preserve

### AgentExecution

`agent_execution.py` already implements Frozen states/phases and project-neutral IA PROMPT admission.

P5 shall drive the existing phase fields rather than add a new planning-run aggregate.

### RuntimeJob

P4 `ae_runtime_job` supports:

```text
START_EXECUTION
CONTINUE_EXECUTION
```

These are sufficient for initial P5 planning/step progression.

P5 need not widen job types unless clarification resume is implemented.

### ExecutableStep

P4 `ae_executable_step` currently has:

```text
step_kind = P4_CHAT_RAG_COMPATIBILITY
UNIQUE (tenant_id, agent_execution_id, step_kind)
```

This is the primary schema blocker for P5 multi-step execution.

### AgentResult

P4 `agent_results.py` creates immutable AgentResult + required PENDING `WORKSPACE_RESULT`.

P5 must defer final AgentResult creation until plan-level completion.

### Intent / Runtime Policy

Current:

```text
intent_policy.py
runtime_policy.py
```

already provide deterministic intent/execution-mode/runtime-policy behavior.

They are mandatory compatibility inputs, not code to discard.

---

## 3. P5 Contract Extraction Deliverable

P5-CA01 produced the reviewed implementation note and machine contracts for:

```text
WorkIntent fields/status
AgentContext fields/version semantics
AgentPlan / PlanStep exact Frozen vocabulary
Plan Validator decision vocabulary
ExecutablePlan required fields
ExecutableStep executor-kind vocabulary
StepResult required fields/status
Frozen bounds / max-step semantics
```

The implementation-facing transition contracts are under:

```text
docs/transition/P5/contracts/
```

They are explicitly labeled transition contracts and do not modify or replace
the Frozen set.

Canonical P5 hash serialization is UTF-8 canonical JSON with sorted keys,
compact separators, `ensure_ascii=false`, `allow_nan=false`, then SHA-256 as
`sha256:<64 lowercase hex>`.

---

## 4. Recommended Source Structure

Exact filenames are reviewable, but recommended logical boundaries are:

```text
services/nex-ae-api/nex_ae_api/planning/
  models.py
  intent_resolver.py
  context_builder.py
  capability_catalog.py
  plan_builder.py
  plan_validator.py
  compiler.py
  executable_plan.py
  step_results.py
  step_engine.py
  executors/
    compatibility.py
    deterministic_report.py
```

Existing modules remain owners of:

```text
agent_execution.py
runtime_jobs.py
agent_results.py
chat_application.py
retrieval.py
runtime_policy.py
```

Avoid growing all planning logic into `agent_runtime_foundation.py`.

---

## 5. Recommended Additive Migration Plan

### 2101 — WorkIntent

Create:

```text
ae_work_intent
```

Suggested:

```text
tenant_id
work_intent_id
agent_execution_id
schema_version
intent_revision
supersedes_work_intent_id
intent_envelope_json
intent_hash
created_at
PRIMARY KEY (tenant_id, work_intent_id)
UNIQUE (tenant_id, agent_execution_id, intent_revision)
```

Do not store raw prompt if Conversation/Interaction already owns it.

### 2102 — AgentContext

Create:

```text
ae_agent_context
```

Suggested:

```text
tenant_id
agent_context_id
agent_execution_id
work_intent_id
context_generation
context_envelope_json
context_hash
created_at
UNIQUE (tenant_id, agent_execution_id, context_generation)
```

### 2103 — Capability Snapshot + AgentPlan + Validation

Create:

```text
ae_capability_catalog_snapshot
ae_agent_plan
ae_plan_validation
```

Plan rows preserve complete immutable envelope/hash.

Capability snapshots are tenant-scoped and immutable. Initial internal IDs are
`AE.CHAT.COMPATIBILITY` and `AE.RESULT.REPORT`; no implicit latest lookup is
permitted.

Validation is a separate record; do not mutate plan to "VALID".

### 2104 — ExecutablePlan

Create:

```text
ae_executable_plan
```

Bind exact plan/context/catalog/compiler versions and hash.

### 2105 — ExecutableStep Generalization

Alter/generalize existing `ae_executable_step`.

Required design work:

- remove/replace P4-only `step_kind` CHECK while preserving the historical
  `P4_CHAT_RAG_COMPATIBILITY` executor value;
- remove/replace `ux_ae_step_execution_kind`;
- preserve existing P4 rows;
- add nullable-for-history/new-required fields:
  - `executable_plan_id`
  - `logical_step_id`
  - `step_index`
  - `executor_kind`
  - `required_capability`
  - `capability_version`
  - dependency/input/output contract metadata
  - step contract hash;
- add uniqueness by executable plan/step index and semantic materialization;
- allow `legacy_interaction_id` to be null only for non-compatibility steps;
- enforce new P5 row completeness without invalidating historical rows.

PostgreSQL is canonical. SQLite may require table rebuild in test adapters.

### 2106 — StepResult

Create:

```text
ae_step_result
```

One immutable result per terminal executable step semantic outcome.

---

## 6. Implementation Slices

### P5-S1 — Transition Contracts + WorkIntent + Prompt Registry Hardening

Implement:

- extracted P5 WorkIntent contract;
- `IntentDecision v1` → WorkIntent adapter;
- WorkIntent repository/hash;
- clarification reasons/questions;
- no authoritative entity ID fabrication;
- canonical hash utility and schema validation;
- prompt template version insert-or-verify semantics;
- explicit prompt binding history;
- exact enabled-stage prompt execution provenance.

Tests:

- four current modes;
- explicit mode;
- retrieval promotion;
- unresolved Project/entity;
- deterministic hash;
- privacy;
- same-version same-content idempotency;
- same-version changed-content rejection;
- binding activation/rollback history;
- deterministic stages do not resolve unused prompt purposes.

Run Slice Gate.

---

### P5-S2 — AgentContext

Implement:

- base context builder;
- trusted resolver ports;
- immutable/versioned context snapshots;
- context provenance/hash;
- WAITING_INPUT on required unresolved authority.

Do not perform cross-service DB joins.

Tests:

- owner/tenant isolation;
- resolved/unresolved selector;
- context version;
- deterministic hash;
- no raw secrets.

Run Slice Gate.

---

### P5-S3 — Capability Catalog + Deterministic Plan Profiles

Implement:

- immutable capability snapshot;
- exact capability version binding;
- deterministic Plan Builder for current v1 modes;
- at least one multi-step profile;
- optional LLM planner protocol only, disabled by default.

Use Frozen plan kinds `DIRECT / CERTIFIED_BINDING / KNOWN_TEMPLATE / DYNAMIC`.
P5 deterministic profiles use `DIRECT` and `KNOWN_TEMPLATE` only.

Do not publish capability IDs as external stable API until reviewed.

Tests:

- snapshot hash;
- no latest;
- known plan profiles;
- plan repeatability;
- unsupported capability.

Run Slice Gate.

---

### P5-S4 — Plan Validator

Implement deterministic validation:

- identity/context binding
- unique logical IDs
- dependency existence
- DAG/cycle
- input binding
- plan bound
- executor availability
- P5 scope guard (`DELEGATE_WORK`, WRITE, NSL unavailable)
- exact Frozen plan/step vocabulary and 12-step bound

Persist validation outcome separately.

Tests include all negative cases.

Run Slice Gate.

---

### P5-S5 — Deterministic Compiler / ExecutablePlan

Implement:

- exact plan/context/catalog binding;
- deterministic compile;
- ExecutablePlan persistence/hash;
- logical-step → executable-step materialization;
- P4 historical-step compatibility migration.

New P5 compatibility work compiles as:

```text
LOCAL_CAPABILITY(AE.CHAT.COMPATIBILITY)
-> CANONICAL_CAPABILITY / P4_CHAT_RAG_COMPATIBILITY
```

No executor invocation during compile.

Checkpoint Gate after this Slice.

---

### P5-S6 — Durable Multi-Step Engine / StepResult

Implement:

- generalized ExecutableStep;
- StepResult;
- deterministic ready-step scheduling;
- `CONTINUE_EXECUTION` per step/progression;
- restart-safe execution;
- no duplicate terminal step execution;
- fail/blocked propagation.

Initial engine executes serial-ready order.

Run Slice Gate.

---

### P5-S7 — Executors / Existing Chat-RAG Integration

Mandatory executors:

1. P4 Chat/RAG compatibility executor
2. deterministic report/aggregation executor

Optional:

- explicit retrieval executor
- explicit model/generation executor

Only implement optional split if regression remains safe.

At least one acceptance scenario must execute 2+ persisted steps.

Run Slice Gate.

---

### P5-S8 — Plan-Level Result Verification / Synthesis

Move canonical AgentResult finalization to plan terminalization:

```text
required StepResults complete
→ completion criteria verified
→ result synthesis
→ AgentResult
→ existing PENDING ResultDelivery
```

Intermediate steps never create final AgentResult.

Preserve P4 result/publication guard.

Run Slice Gate.

---

### P5-S9 — Closure

Run:

- Full Gate
- protected PostgreSQL planning/runtime smoke
- existing P4 runtime regression
- existing authenticated Chat/RAG Playwright
- invalid-plan negative pack
- restart/no-duplicate step tests
- explicit zero-NSL-invocation audit
- Frozen checksum/integrity checks

Publish P5 closure report.

---

## 7. Protected PostgreSQL Smoke

Smoke SHALL prove real persisted effects:

1. apply P4 + P5 migrations;
2. create/admit one project-neutral IA AgentExecution;
3. persist WorkIntent;
4. persist AgentContext;
5. persist capability snapshot;
6. build and validate AgentPlan;
7. compile ExecutablePlan;
8. materialize 2+ steps;
9. execute first step and persist StepResult;
10. restart repository/runtime boundary;
11. execute dependent step exactly once;
12. persist final AgentResult only after plan completion;
13. verify required ResultDelivery remains PENDING;
14. verify AgentExecution is not SUCCEEDED;
15. clean smoke-owned rows and prove zero residue.

---

## 8. Rollout

Recommended:

```text
NEX_AE_PLANNING_MODE=disabled|shadow|required
```

### disabled
P4 compatibility behavior only.

### shadow
Build/validate/compile Plan for evidence, but legacy compatibility execution remains response-authoritative. Shadow plan must not cause extra provider/business side effects.

### required
Every admitted P5 execution requires:

```text
WorkIntent
AgentContext
AgentPlan
validation status=VALID
ExecutablePlan
durable step engine
```

before final result.

---

## 9. P5-CA01 Answers to Pre-Implementation Questions

1. P5 uses `work_intent_id`, immutable revision, PROMPT-only source, separate
   Frozen `INTERACTIVE` mode and current compatibility execution mode, explicit
   provenance, and no raw prompt duplication.
2. AgentContext is an immutable generation with exact WorkIntent, identity,
   interaction, optional Project/entity, evidence, policy, manifest, budget,
   and hash bindings.
3. Logical types are `LOCAL_CAPABILITY / DELEGATE_WORK / AGGREGATE / REPORT`;
   executable types are the seven Frozen Doc 05 types. P5 activates only
   `CANONICAL_CAPABILITY / AGGREGATE / REPORT`.
4. `max_plan_steps=12`, `max_delegation_depth=0`, and
   `max_parallel_steps=1` for P5 closure.
5. Provenance includes route/builder, exact capability snapshot, input context
   hash, and exact prompt/model hashes only when an LLM stage is enabled.
6. Migration 2105 preserves historical rows, removes P4-only constraints, adds
   nullable historical/new-required planning fields, and uses dual-dialect
   regression.
7. Initial internal IDs are `AE.CHAT.COMPATIBILITY` and `AE.RESULT.REPORT`.
8. `GENERAL_ANSWER` is one-step `DIRECT`; the other three modes use a two-step
   `KNOWN_TEMPLATE` compatibility-plus-report profile.
9. P5 persists clarification and `WAITING_INPUT`; resume is deferred and no
   `RESUME_EXECUTION` job type is added.
10. Plan terminalization verifies required StepResults before invoking the P4
    AgentResult/ResultDelivery handoff.
11. Scope guards reject `LOCAL_SKILL`, no NSL adapter is registered, and closure
    audits provider/port call evidence for zero NSL invocation.
12. `NEX_AE_PLANNING_MODE=disabled` returns to P4 response-authoritative
    behavior; shadow mode creates no extra provider/business side effects.

---

## 10. P5 Exit Gate

P5 is ready to close when one real AgentExecution demonstrates:

```text
Prompt
→ WorkIntent
→ AgentContext
→ AgentPlan
→ validation status=VALID
→ ExecutablePlan
→ 2+ persisted ExecutableSteps
→ ordered durable execution
→ StepResults
→ AgentResult
```

with:

- P4 regression PASS;
- restart safety;
- deterministic plan/compiler hashes;
- no fake IDs;
- no WC;
- no NSL;
- no false SUCCEEDED while delivery ACK is pending.
