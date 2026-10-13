# P5 Transition Machine Contracts v1.1

**Status:** P5-CA01A REVIEWED TRANSITION CONTRACTS

These schemas are the P5 v1.1 implementation-facing transition shapes:

- `p5-work-intent-v1.1.schema.json`
- `p5-agent-context-v1.1.schema.json`
- `p5-capability-snapshot-v1.1.schema.json`
- `p5-agent-plan-v1.1.schema.json`
- `p5-plan-validation-result-v1.1.schema.json`
- `p5-executable-plan-v1.1.schema.json`
- `p5-step-result-v1.1.schema.json`

Authority:

```text
Frozen Agent/Platform semantics
> P5-CA01/CA01A decisions
> P5 v1.1 transition schemas
> legacy 99_* reference schemas
```

## CA01A contract rules

```text
LogicalPlanStepId = S1...
CompiledStepKey   = E1...
ExecutableStepId  = UUID
```

Dependencies in ExecutablePlan use `CompiledStepKey`.
Runtime persistence uses UUID `ExecutableStepId`.

Semantic ExecutablePlan hashing excludes runtime UUIDs.

Hash representation:

```text
legacy/existing *_sha256 digest = bare 64 hex
P5 semantic *_hash              = sha256:<64 hex>
```

PlanValidationResult includes one required `runtime_directive` matching its status.

P5 StepResult requires:

```text
business_operation_id = null
operation_fingerprint = null
```

Schema visibility of future vocabulary is not runtime availability.
