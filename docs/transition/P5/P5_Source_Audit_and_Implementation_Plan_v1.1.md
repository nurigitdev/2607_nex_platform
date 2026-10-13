# P5 Source Audit and Implementation Plan v1.1

**Status:** P5-CA01A REVIEWED IMPLEMENTATION BASELINE

**Supersedes:** v1.0

**Implementation state:** IN PROGRESS — P5-S1..P5-S4 COMPLETE

## 1. Entry baseline

P5-S1 starts only from:

- P5-CA01 v1.1;
- P5-CA01A closure;
- v1.1 transition schemas;
- completed P4 As-Built source.

## 2. P4 facts preserved

- AgentExecution state/phase vocabulary is already implemented.
- RuntimeJob supports START/CONTINUE.
- P4 ExecutableStep runtime identity is UUID.
- current `ae_executable_step` is one compatibility row and must be generalized later without changing historical UUIDs.
- AgentResult + PENDING WORKSPACE_RESULT boundary remains.
- existing IntentPolicy/RuntimePolicy are compatibility inputs.

## 3. Migration plan

### 2100 — Prompt Registry hardening

Add `ae_prompt_binding_history` and indexes/constraints needed for atomic binding changes.

Repository behavior:

- immutable version insert-or-verify;
- lock/CAS current binding;
- history INSERT + pointer UPDATE in one transaction.

### 2101 — WorkIntent

Immutable revisioned `ae_work_intent`.

### 2102 — AgentContext

Immutable generation `ae_agent_context`.

### 2103 — Capability Snapshot + AgentPlan + Validation

```text
ae_capability_snapshot
ae_agent_plan
ae_plan_validation
```

PlanValidation stores required runtime directive.

### 2104 — ExecutablePlan

`ae_executable_plan` stores semantic envelope/hash.

### 2105 — ExecutableStep generalization

Preserve UUID `executable_step_id`.

Add:

```text
executable_plan_id
logical_step_id
compiled_step_key
step_index
step_type
executor_kind
required_capability
capability_version
dependency/input/output metadata
step_contract_hash
```

New P5 unique semantic key:

```text
(tenant_id, executable_plan_id, compiled_step_key)
```

P4 historical rows remain readable.

### 2106 — StepResult

Store UUID ExecutableStep lineage + compiled E-key + logical S-key.

P5 CHECK/domain validation requires:

```text
business_operation_id IS NULL
operation_fingerprint IS NULL
```

## 4. Shared hash utility — S1

Create one shared utility supporting:

```text
validate_sha256_digest()
validate_hash_ref()
hash_ref_from_sha256()
sha256_from_hash_ref()
semantic_sha256_hash_ref(canonical_json_object)
```

Tests must prove representation conversion does not rehash.

## 5. Slice plan

### P5-S1 — WorkIntent + Prompt Registry hardening

**Status:** COMPLETE — 2026-10-13

Implement:

- v1.1 WorkIntent contract;
- existing IntentDecision adapter;
- shared hash utility;
- Prompt immutable version insert-or-verify;
- atomic binding history/pointer transaction;
- exact prompt provenance.

### P5-S2 — AgentContext

**Status:** COMPLETE — 2026-10-13

Implement immutable generation/context hash/trusted resolver boundary.

### P5-S3 — Capability Snapshot + deterministic profiles

**Status:** COMPLETE — 2026-10-13

Implement exact-version capability snapshot and DIRECT/KNOWN_TEMPLATE plans.

Implemented physical tables use the concise names `ae_capability_snapshot`,
`ae_agent_plan`, and `ae_plan_validation`; the first remains the durable
representation of the logical Capability Catalog Snapshot.

### P5-S4 — Plan Validator

**Status:** COMPLETE — 2026-10-13

Implement all validation rules plus exact CA01A runtime mapping.

Important:

```text
REPLAN_REQUIRED does NOT call planner again.
CONTEXT_REFRESH_REQUIRED does NOT enter auto-refresh loop.
RETRYABLE_VALIDATION_FAILURE is bounded technical retry only.
```

Implemented validation is deterministic and LLM-free. Validation persistence
and the mapped AgentExecution state/phase transition share one transaction and
use execution-version CAS. Only `VALID / PROCEED_TO_COMPILE` grants compile
authority; the validator does not create compile rows or call a planner.

### P5-S5 — Deterministic Compiler / ExecutablePlan

Implement `S-key → E-key → UUID` mapping.

Semantic hash excludes UUID.

Generalize P4 table safely.

### P5-S6 — Multi-Step Engine / StepResult

Persist StepResult with:

```text
ExecutableStepId UUID
CompiledStepKey E*
LogicalPlanStepId S*
WRITE fields null
```

### P5-S7 — Executors

Compatibility executor + deterministic report/aggregate executor.

### P5-S8 — Plan-level finalization

Required StepResults → completion verification → AgentResult → PENDING delivery.

### P5-S9 — Closure

Full regression, PostgreSQL smoke, restart/dedup tests, zero NSL audit.

## 6. Mandatory P5-S1 fault tests

- prompt version same-content idempotency;
- prompt version changed-content conflict;
- binding history insert failure → pointer unchanged;
- pointer update failure → history rolled back;
- concurrent binding change expected-current conflict;
- hash representation round trip / no double hash.

## 7. Mandatory P5-S4 mapping tests

All seven statuses must assert:

- runtime directive;
- AgentExecution state;
- AgentExecution phase;
- zero compile on non-VALID;
- no automatic semantic replan.

## 8. Mandatory P5-S5 determinism test

Compile the same semantic input twice with different runtime UUID factories.

Expected:

```text
same CompiledStepKeys
same dependency graph
same step contract hashes
same ExecutablePlan semantic hash
possibly different ExecutableStep UUIDs
```

## 9. Exit gate

One real execution proves:

```text
Prompt
→ WorkIntent
→ AgentContext
→ AgentPlan
→ VALID / PROCEED_TO_COMPILE
→ ExecutablePlan
→ S-key/E-key/UUID step lineage
→ 2+ durable steps
→ StepResults with null WRITE fields
→ AgentResult
```

with P4 regression PASS and no NSL/WC/WRITE.
