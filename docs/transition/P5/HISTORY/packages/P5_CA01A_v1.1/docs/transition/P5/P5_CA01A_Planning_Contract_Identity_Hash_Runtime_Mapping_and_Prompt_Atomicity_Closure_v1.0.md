# P5-CA01A Planning Contract Identity, Hash, Runtime Mapping and Prompt Atomicity Closure v1.0

**Status:** APPROVED PRE-IMPLEMENTATION CONSISTENCY CLOSURE  
**Phase:** P5 — Agent Planning & Execution Foundation  
**Decision date:** 2026-10-13  
**Predecessor:** P5-CA01 Frozen Planning Contract Extraction and Pre-Implementation Design Closure v1.0  
**Effect:** P5 v1.1 transition baseline

---

## 1. Purpose

P5-CA01A closes five machine-contract and runtime-mapping ambiguities found after P5-CA01 review.

It does not change the Frozen Platform/Agent/NSL product architecture.

The five closures are:

1. separate `ExecutableStepId` runtime identity from deterministic compiled step key;
2. define bare SHA-256 ↔ prefixed semantic hash interoperability;
3. map PlanValidation status deterministically to AgentExecution state/phase/runtime directive;
4. require all P5 StepResult WRITE-related fields to be explicit null;
5. make Prompt binding-history creation and binding-pointer update one atomic transaction.

---

## 2. CA01A-DEC-01 — ExecutableStep identity separation

P4 already established:

```text
ExecutableStepId = UUID runtime identity
```

P5 SHALL preserve it.

P5 introduces a distinct deterministic compiled key:

```text
LogicalPlanStepId = S1, S2, ...
CompiledStepKey   = E1, E2, ...
ExecutableStepId  = UUID
```

Example:

```text
AgentPlan logical step
S1
 ↓ compile
ExecutablePlan semantic step
compiled_step_key = E1
 ↓ materialize
Runtime ExecutableStep
executable_step_id = 550e8400-e29b-41d4-a716-446655440000
```

### Dependency semantics

`ExecutablePlan` dependencies SHALL use `compiled_step_key`.

Runtime persistence MAY resolve those keys to UUID ExecutableStep rows.

### Hash semantics

Generated runtime UUID values SHALL NOT determine the semantic ExecutablePlan hash.

The semantic hash projection SHALL include:

- `compiled_step_key`
- logical step reference
- executor/capability/version binding
- dependency compiled-step keys
- compiled input bindings
- output contract
- deterministic step contract hash

and SHALL exclude:

- `executable_step_id`
- row timestamps
- persistence-only runtime identities

This preserves deterministic compilation even when runtime UUID allocation differs.

---

## 3. CA01A-DEC-02 — SHA-256 interoperability

NeX v1/P4 contains existing digest fields stored as bare lowercase SHA-256 hex:

```text
^[0-9a-f]{64}$
```

P5 semantic object hashes use canonical hash references:

```text
sha256:<64 lowercase hex>
```

P5 SHALL preserve both representations with explicit type distinction.

### Bare digest

Use for existing or explicitly named SHA-256 digest fields:

```text
content_sha256
prompt_content_sha256
rendered_prompt_hash when stored in existing Prompt Registry
intent_decision_hash from existing IntentDecision v1
output_hash from existing prompt render event
```

Representation:

```text
abcdef0123...
```

### Semantic hash reference

Use for P5 semantic object hashes:

```text
intent_hash
context_hash
capability_snapshot_hash
plan_hash
validation_result_hash
executable_plan_hash
step_contract_hash
step_result_hash
binding_hash
```

Representation:

```text
sha256:abcdef0123...
```

### Conversion

Conversion SHALL occur through one shared utility:

```text
hash_ref_from_sha256(bare_digest)
→ "sha256:" + bare_digest

sha256_from_hash_ref(hash_ref)
→ bare digest
```

No feature module SHALL hand-build or strip the prefix independently.

### No double hashing

Conversion between forms changes representation only.

It MUST NOT hash the digest again.

---

## 4. CA01A-DEC-03 — PlanValidation deterministic runtime mapping

P5 fixes the following mapping.

| PlanValidation status | Runtime directive | AgentExecution state | AgentExecution phase | P5 behavior |
|---|---|---|---|---|
| `VALID` | `PROCEED_TO_COMPILE` | `RUNNING` | `PLAN_COMPILE` | compile exactly the validated Plan |
| `CLARIFICATION_REQUIRED` | `WAIT_FOR_INPUT` | `WAITING_INPUT` | `PLAN_VALIDATE` | persist questions; zero executable steps |
| `REPLAN_REQUIRED` | `BLOCK_REPLAN_REQUIRED` | `BLOCKED` | `PLAN_VALIDATE` | P5 does not auto-replan |
| `CONTEXT_REFRESH_REQUIRED` | `BLOCK_CONTEXT_REFRESH_REQUIRED` | `BLOCKED` | `PLAN_VALIDATE` | P5 does not enter an unbounded refresh loop |
| `BLOCKED` | `BLOCK_EXECUTION` | `BLOCKED` | `PLAN_VALIDATE` | no compile |
| `INVALID_TERMINAL` | `FAIL_VALIDATION` | `FAILED` | `PLAN_VALIDATE` | terminal invalid Plan |
| `RETRYABLE_VALIDATION_FAILURE` | `RETRY_VALIDATION_BOUNDED` | `RUNNING` | `PLAN_VALIDATE` | bounded technical retry only |

### Retry rule

`RETRYABLE_VALIDATION_FAILURE` is a technical validation failure, not semantic replan authority.

Retry:

- reuses the same AgentPlan;
- does not call an LLM Plan Builder again;
- uses the existing runtime retry budget/policy;
- records a new validation attempt/result as required by implementation;
- on retry-budget exhaustion transitions to `FAILED / PLAN_VALIDATE`.

P5 automatic semantic replan count remains:

```text
max_auto_replan = 0
```

---

## 5. CA01A-DEC-04 — P5 StepResult WRITE-field nullability

The P5 StepResult schema retains future WRITE vocabulary for forward compatibility:

```text
business_operation_id
operation_fingerprint
```

P5 has no WRITE authority.

Therefore every P5-created StepResult SHALL explicitly satisfy:

```text
business_operation_id = null
operation_fingerprint = null
```

The v1.1 transition schema SHALL require both fields and enforce `const: null`.

P6 READ integration is expected to preserve the same null values.

Non-null values are reserved for later WRITE phases and require a controlled contract update.

A P5 executor returning a non-null WRITE field SHALL fail contract validation before StepResult persistence.

---

## 6. CA01A-DEC-05 — Prompt binding atomicity

PromptTemplateVersion remains immutable.

PromptBinding remains the mutable deployment pointer.

Any binding change SHALL atomically persist both:

1. durable binding-change history;
2. the new current binding pointer.

Required transaction:

```text
BEGIN

SELECT current binding ... FOR UPDATE

validate target exact PromptTemplateVersion

INSERT ae_prompt_binding_history (
    binding_change_id,
    binding_key,
    old_prompt_template_version_id,
    new_prompt_template_version_id,
    changed_by,
    reason,
    correlation_id,
    changed_at
)

UPDATE ae_prompt_bindings
SET prompt_template_version_id = :new_version,
    bound_at = :changed_at
WHERE binding_key = :binding_key

COMMIT
```

If either history insert or pointer update fails, both SHALL roll back.

### Idempotency

Requesting the already-current version is an idempotent no-op.

It SHALL NOT create misleading duplicate history unless an explicit audited no-op event is separately required.

### Concurrency

Binding change SHALL lock or compare the expected current version so that two concurrent operators cannot silently overwrite each other.

### Runtime isolation

An AgentExecution/WorkIntent/AgentPlan that already captured an exact prompt version/hash SHALL continue using that captured version even if the binding changes later.

---

## 7. Contract Changes

P5 v1.1 transition contracts SHALL apply:

### `p5-work-intent-v1.1.schema.json`
- distinguish existing bare digest fields from P5 semantic hash refs.

### `p5-agent-plan-v1.1.schema.json`
- same hash interoperability rule for prompt provenance.

### `p5-plan-validation-result-v1.1.schema.json`
- add required deterministic `runtime_directive`;
- constrain status/directive pairs.

### `p5-executable-plan-v1.1.schema.json`
- add `compiled_step_key`;
- change `executable_step_id` to UUID;
- use compiled-step keys for semantic dependencies/completion mapping;
- preserve UUID only as runtime identity.

### `p5-step-result-v1.1.schema.json`
- `executable_step_id` = UUID;
- add `compiled_step_key`;
- require WRITE-related fields and enforce null.

---

## 8. Implementation Ownership

P5-S1 owns:

- hash interoperability utility;
- Prompt version immutability;
- atomic binding history/pointer update.

P5-S4 owns:

- validation status/runtime mapping.

P5-S5 owns:

- compiled-step-key / UUID separation in compiler and ExecutablePlan;
- P4 `ae_executable_step` migration.

P5-S6 owns:

- StepResult UUID/key lineage;
- WRITE-field null enforcement.

---

## 9. Acceptance

P5-CA01A closes when:

- all v1.1 schemas validate;
- P4 UUID ExecutableStep identity is preserved;
- deterministic compile hashes do not depend on runtime UUID;
- bare/prefixed SHA forms are never confused or double-hashed;
- all seven validation statuses have one deterministic P5 runtime mapping;
- P5 StepResult rejects non-null WRITE fields;
- prompt binding history and pointer update pass transaction fault/concurrency tests.

> P5-CA01A is a contract/runtime mapping closure, not feature implementation evidence.
