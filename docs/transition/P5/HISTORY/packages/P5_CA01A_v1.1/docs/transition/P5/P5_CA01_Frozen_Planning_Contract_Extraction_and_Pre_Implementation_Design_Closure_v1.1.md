# P5-CA01 Frozen Planning Contract Extraction and Pre-Implementation Design Closure v1.1

**Status:** APPROVED PRE-IMPLEMENTATION CLOSURE — CA01A INCORPORATED  
**Phase:** P5 — Agent Planning & Execution Foundation  
**Decision date:** 2026-10-13  
**Supersedes:** P5-CA01 v1.0

## 1. Purpose

This v1.1 baseline preserves every P5-CA01 design decision and incorporates P5-CA01A identity/hash/runtime/prompt-atomicity closure.

No file under `docs/frozen/v2.1/` is changed by this transition baseline.

## 2. Authority

```text
Integrated Frozen v2.1 baseline
> approved P4-CA01 project-neutral PROMPT amendment
> P5-CA01 v1.1 + P5-CA01A closure
> P5 v1.1 transition machine contracts
> remaining P5 v1.1 design documents
> legacy reference schemas
> implementation convenience
```

## 3. Retained CA01 decisions

P5 retains the CA01 decisions for:

- WorkIntent immutable revision and PROMPT-only transition contract;
- AgentContext immutable generation snapshot;
- tenant-scoped immutable capability snapshot;
- Frozen plan kinds `DIRECT / CERTIFIED_BINDING / KNOWN_TEMPLATE / DYNAMIC`;
- logical step types `LOCAL_CAPABILITY / DELEGATE_WORK / AGGREGATE / REPORT`;
- executable step types `LOCAL_SKILL / CANONICAL_CAPABILITY / DELEGATE_WORK / HUMAN_CONFIRMATION / FORMAL_APPROVAL / AGGREGATE / REPORT`;
- `max_plan_steps=12`, `max_delegation_depth=0`, `max_parallel_steps=1`;
- deterministic plan profiles for the four compatibility execution modes;
- Frozen validation status vocabulary;
- immutable StepResult semantic outcome;
- Prompt Registry immutable exact-version model;
- clarification persistence with resume deferred;
- P4 executable-step historical-row-safe migration;
- AgentResult finalization only after plan completion.

## 4. CA01A incorporated decisions

### 4.1 Step identity

```text
LogicalPlanStepId = S1...
CompiledStepKey   = E1...
ExecutableStepId  = UUID
```

`CompiledStepKey` is deterministic within one ExecutablePlan and is used for semantic dependencies/hashing.

`ExecutableStepId` is the durable P4/P5 runtime identity.

### 4.2 Hash profile

```text
existing/persisted digest fields named *_sha256 = bare 64 lowercase hex
P5 semantic object *_hash                         = sha256:<64 lowercase hex>
```

Representation conversion is centralized and never double-hashes.

### 4.3 Validation runtime mapping

P5 uses this exact mapping:

| Status | Directive | State | Phase |
|---|---|---|---|
| `VALID` | `PROCEED_TO_COMPILE` | `RUNNING` | `PLAN_COMPILE` |
| `CLARIFICATION_REQUIRED` | `WAIT_FOR_INPUT` | `WAITING_INPUT` | `PLAN_VALIDATE` |
| `REPLAN_REQUIRED` | `BLOCK_REPLAN_REQUIRED` | `BLOCKED` | `PLAN_VALIDATE` |
| `CONTEXT_REFRESH_REQUIRED` | `BLOCK_CONTEXT_REFRESH_REQUIRED` | `BLOCKED` | `PLAN_VALIDATE` |
| `BLOCKED` | `BLOCK_EXECUTION` | `BLOCKED` | `PLAN_VALIDATE` |
| `INVALID_TERMINAL` | `FAIL_VALIDATION` | `FAILED` | `PLAN_VALIDATE` |
| `RETRYABLE_VALIDATION_FAILURE` | `RETRY_VALIDATION_BOUNDED` | `RUNNING` | `PLAN_VALIDATE` |

`max_auto_replan=0` in P5.

### 4.4 P5 StepResult WRITE fields

Every P5 StepResult explicitly carries:

```text
business_operation_id = null
operation_fingerprint = null
```

Non-null is a contract violation.

### 4.5 Prompt binding atomicity

Binding history INSERT and current binding UPDATE are one DB transaction with lock/CAS protection.

Existing in-flight Agent semantic artifacts use their captured exact prompt version/hash after later binding changes.

## 5. P5 transition contracts

P5 v1.1 implementation SHALL use contracts under:

```text
docs/transition/P5/contracts/*v1.1.schema.json
```

The v1.0 P5 contracts are historical transition artifacts after v1.1 adoption.

## 6. Implementation entry gate

P5-S1 may begin when:

- v1.1 contracts validate;
- CA01A rules are reflected in SRS/plan/traceability;
- no module still treats `E1` as Runtime ExecutableStep UUID;
- hash type conversion is designed as a shared utility;
- prompt binding transaction semantics are included in S1.

> P5-CA01 v1.1 + P5-CA01A close the P5 design entry gate. They do not claim P5 source implementation.
