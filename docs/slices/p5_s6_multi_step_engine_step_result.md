# P5-S6 Multi-Step Engine and StepResult

## Scope

- Reuse the P4 `START_EXECUTION` / `CONTINUE_EXECUTION` RuntimeJob queue.
- Schedule and claim one persisted ExecutableStep at a time in deterministic
  compiled order.
- Materialize one immutable terminal StepResult for every terminal step.
- Propagate failed, cancelled, or blocked dependencies without invoking their
  downstream executors.
- Move a fully terminal plan to `RUNNING / RESULT_VERIFY` for P5-S8.

P5-S6 does not execute Chat/RAG, report, or aggregate logic. Those executor
adapters belong to P5-S7.

## Runtime Rules

- Scheduling requires an exact tenant-scoped AgentExecution and latest
  ExecutablePlan.
- AgentExecution authority is `RUNNING / PLAN_COMPILE` or
  `RUNNING / STEP_EXECUTION`.
- At most one ExecutableStep may be `READY` or `RUNNING`.
- The first materialized step uses `START_EXECUTION`; later steps use
  `CONTINUE_EXECUTION`.
- RuntimeJob dedup identity is
  `p5:step:{executable_plan_id}:{compiled_step_key}`.
- A successful dependency promotes the next eligible `PENDING` step to
  `READY` by versioned compare-and-swap.
- A terminal non-success creates immutable `BLOCKED` StepResults for all
  transitively dependent steps.
- Restarting after a terminal write returns the existing result and never
  invokes the executor again.

## StepResult Contract

Migration `2106_ae_step_result.sql` creates the concise table
`ae_step_result` with unique `(tenant_id, executable_step_id)` ownership and
foreign keys to AgentExecution, ExecutablePlan, and ExecutableStep.

Each result preserves:

```text
ExecutableStepId UUID
CompiledStepKey   E1...
LogicalStepId     S1...
attempt_no
terminal status
result contract and payload/reference envelope
sha256:<64 hex> semantic result hash
```

`business_operation_id` and `operation_fingerprint` are mandatory JSON nulls
and database nulls. P5 therefore cannot claim NSL WRITE identity.

The semantic result hash excludes generated StepResult UUID and database-time
metadata, while retaining exact execution/plan/step lineage, attempt, status,
contract, payload, references, and null WRITE fields.

## Persistence And Failure Safety

- Terminal step state and StepResult insertion share one transaction.
- Result replay is idempotent only when semantic content is identical.
- UUID reuse, step uniqueness, lineage drift, malformed stored JSON, missing
  dependencies, parallel active steps, and CAS conflicts fail closed.
- PostgreSQL uses JSONB casts while SQLite remains the fast deterministic
  regression backend.
- Store failures are retryable infrastructure errors; contract and lineage
  failures remain non-retryable domain errors.

## Verification

- Focused S6 tests: `58 passed` across StepResult, multi-step engine, migration,
  and protected-smoke contracts.
- `nex_ae_api.step_results` and `nex_ae_api.multi_step_engine` each reached
  `100%` statement and `100%` branch coverage in focused tests.
- Actual PostgreSQL smoke connected as `nex_ae_user@nex_ae_test`, applied the
  complete `38`-migration inventory, and passed `18/18` checks.
- The smoke persisted and claimed one START plus one CONTINUE RuntimeJob,
  handed the E1 result to E2, persisted two immutable StepResults, verified
  result replay and restart no-reexecution, and left zero tenant residue.
- AE Slice Gate passed with `3438 passed`, `5` protected opt-in tests skipped;
  statement coverage `98.58%`, branch coverage `96.76%`.
- Contract validation passed `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents.
- Remote model providers were not required because S6 owns orchestration and
  persistence rather than executor behavior.

## Deferred

- P5-S7 owns the P4 Chat/RAG compatibility executor and deterministic
  report/aggregate executors.
- P5-S8 owns required-result verification, AgentResult synthesis, and PENDING
  WORKSPACE_RESULT publication.
- P5-S9 owns full closure, restart/dedup acceptance, and the zero-NSL audit.
