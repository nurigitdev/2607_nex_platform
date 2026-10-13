# P5 Architecture Decisions v1.1

**Status:** P5-CA01A REVIEWED DESIGN BASELINE

**Supersedes:** P5 Architecture Decisions v1.0

---

## Core decisions retained from v1.0

### P5-DEC-01 — Separate canonical Planning Layer
Prompt → WorkIntent → AgentContext → AgentPlan → Validation → ExecutablePlan → ExecutableStep.

### P5-DEC-02 — Unresolved entities are selectors/candidates
LLM/heuristics cannot manufacture authoritative business IDs.

### P5-DEC-03 — Existing deterministic Intent Policy is the first mandatory resolver
`GENERAL_ANSWER | GROUNDED_ANSWER | DOCUMENT_SUMMARY | DOCUMENT_GENERATION` remain compatibility inputs.

### P5-DEC-04 — AgentContext is immutable/versioned and reference-based
No cross-service DB dump; no credentials/provider secrets.

### P5-DEC-05 — Deterministic/template planning precedes dynamic LLM planning
Dynamic LLM planning remains optional/shadow.

### P5-DEC-06 — AgentPlan is never directly executable
Validator + deterministic compiler are mandatory.

### P5-DEC-07 — Reuse P4 runtime identities
No second AgentExecution/RuntimeJob/ExecutableStep hierarchy.

### P5-DEC-08 — LOCAL_SKILL is schema-visible but unavailable in P5
P6 owns the NSL executor.

### P5-DEC-09 — DELEGATE_WORK is not executable in P5
No WC WorkItem creation.

### P5-DEC-10 — Multi-step execution is durable/restart-safe
Terminal succeeded steps are never replayed.

### P5-DEC-11 — Initial DAG execution is deterministic serial-ready order
`max_parallel_steps = 1`.

### P5-DEC-12 — AgentResult is plan-level, not intermediate-step-level
Create final AgentResult only after required plan completion/terminalization.

### P5-DEC-13 — Clarification fails safely
Persist explicit `WAITING_INPUT`; no fabricated values.

### P5-DEC-14 — P5 ends before NSL
No NSP/Skill/NSLExecutionId/WRITE.

### P5-DEC-15 — Frozen plan/step vocabulary comes from CA01 extraction
Legacy `99_*` vocabulary is reference-only.

### P5-DEC-16 — Capability snapshot is tenant-scoped and immutable
No implicit latest.

### P5-DEC-17 — Initial internal capability IDs remain non-public
`AE.CHAT.COMPATIBILITY`, `AE.RESULT.REPORT`.

### P5-DEC-18 — Canonical JSON semantic hashes
P5 semantic object hashes use canonical JSON + SHA-256 hash references.

### P5-DEC-19 — Existing Prompt Registry becomes P5 LLM control plane
RDBMS operational SoR; source seeds bootstrap only; exact-version provenance mandatory.

### P5-DEC-20 — Clarification resume remains deferred
P5 persists wait/questions; no `RESUME_EXECUTION`.

---

## P5-DEC-21 — Runtime ExecutableStep identity is UUID

P5 SHALL preserve P4 runtime identity:

```text
ExecutableStepId = UUID
```

The compiler SHALL also produce a deterministic plan-local key:

```text
CompiledStepKey = E1 | E2 | ...
```

Logical planning key remains:

```text
LogicalPlanStepId = S1 | S2 | ...
```

The three identities MUST NOT be collapsed.

---

## P5-DEC-22 — Semantic compilation uses CompiledStepKey, not UUID

Dependencies, topological semantic order, completion criteria and deterministic plan hashing SHALL use `CompiledStepKey`.

Runtime UUID is excluded from semantic ExecutablePlan hash projection.

This ensures compile determinism while preserving durable UUID runtime identities.

---

## P5-DEC-23 — SHA-256 representation interoperability is explicit

Existing digest fields named `*_sha256` and existing Prompt Registry digest columns retain bare lowercase 64-hex representation.

New P5 semantic `*_hash` values use:

```text
sha256:<64 lowercase hex>
```

Conversion is centralized and never re-hashes an existing digest.

---

## P5-DEC-24 — PlanValidation has deterministic runtime mapping

Every P5 PlanValidation status maps to exactly one runtime directive/state/phase.

P5 performs no automatic semantic replanning:

```text
max_auto_replan = 0
```

Technical retry is distinct from semantic replan.

---

## P5-DEC-25 — P5 StepResult has no WRITE identity

For every P5 StepResult:

```text
business_operation_id = null
operation_fingerprint = null
```

Non-null values are contract violations.

---

## P5-DEC-26 — Prompt binding mutation is atomic and audited

Binding history insertion and current pointer update are one transaction.

Prompt version content remains immutable.

Concurrent binding changes require lock/CAS protection.

Already-running executions use captured exact versions and are unaffected by later binding changes.
