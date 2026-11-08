# P5-S5 Deterministic Compiler and ExecutablePlan

## Scope

- Consume only an issue-free `VALID / PROCEED_TO_COMPILE`
  PlanValidationResult.
- Compile the logical AgentPlan DAG into an immutable ExecutablePlan v1.1.
- Materialize generalized durable ExecutableStep rows without starting step
  execution.
- Preserve exact WorkIntent, AgentContext, Capability Snapshot, AgentPlan, and
  PlanValidation lineage.

## Identity And Determinism

The three step identities have separate responsibilities:

```text
S1... = logical AgentPlan step identity
E1... = deterministic compiled order identity
UUID  = durable ExecutableStep runtime identity
```

- The validator-provided topological order deterministically assigns `E1...`.
- `logical_step_mapping` records the complete `S-key -> E-key -> UUID` lineage.
- Dependencies and step-output bindings are rewritten from S-keys to prior
  E-keys.
- `step_contract_hash` excludes the generated ExecutableStep UUID.
- `executable_plan_hash` excludes the generated ExecutablePlan UUID,
  ExecutableStep UUIDs, `compiled_at`, and the hash field itself.
- Exact upstream versioned references, compiler version, capability version,
  E-key graph, bindings, output contracts, and runtime constraints remain in
  the semantic projection.
- Compiling identical semantic input with different UUID factories and times
  produces identical E-keys, step hashes, and plan hash.

## Compiler Boundary

- Exact persisted `VALID` validation authority is mandatory.
- AgentExecution must remain `RUNNING / PLAN_COMPILE` with its P4 interaction
  bridge present.
- The current P5 compiler resolves exact capability versions from the immutable
  Capability Snapshot. Missing, ambiguous, drifted, or unsupported capability
  paths fail closed.
- `DELEGATE_WORK` remains unavailable in P5.
- P5-S5 does not invoke an LLM or any remote provider.
- P5-S5 does not move AgentExecution to `STEP_EXECUTION`; dependency-aware
  claiming and execution belong to P5-S6.

## Persistence

- Migration `2104_ae_executable_plan.sql` adds the immutable semantic envelope
  table `ae_executable_plan`.
- Migration `2105_ae_executable_step_generalization.sql` generalizes the
  existing P4 `ae_executable_step` table with plan, logical, compiled,
  dependency, binding, capability, contract, and hash columns.
- Historical P4 rows remain valid with all generalized P5 columns null.
- New P5 rows require a complete generalized shape and a unique
  `(tenant_id, executable_plan_id, compiled_step_key)` identity.
- Plan and all steps are inserted and verified in one transaction. A replay of
  the same plan is idempotent; version, immutable-content, lineage, and partial
  materialization conflicts fail closed.
- Dependency-free steps start as `READY`; dependent steps start as `PENDING`.

## Verification

- Focused P5-S5 tests: `50 passed` after including compiler, migration, and
  protected-smoke contract tests.
- `nex_ae_api.executable_plans` reached `100%` statement and `100%` branch
  coverage.
- Actual PostgreSQL smoke used `nex_ae_user@nex_ae_test`, applied the complete
  37-migration inventory, and passed `10/10` checks.
- The smoke persisted one ExecutablePlan and two ExecutableSteps, verified
  `S1/S2 -> E1/E2 -> UUID`, `READY/PENDING` dependency state, semantic hash
  determinism, replay and restart reads, and zero residue after cleanup.
- AE Slice Gate passed with `3388 passed`, `5` protected opt-in tests skipped;
  statement coverage `98.55%`, branch coverage `96.69%`.
- Contract validation passed `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents.

## Deferred

- P5-S6 owns dependency-aware step claiming, AgentExecution phase transition,
  and execution scheduling.
- P5-S6 owns StepResult materialization; P5-S7 owns executor dispatch and P5-S8
  owns AgentResult materialization.
