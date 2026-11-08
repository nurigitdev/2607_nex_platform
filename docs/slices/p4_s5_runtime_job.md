# P4-S5 Canonical RuntimeJob

## Scope

- Adopt the Frozen `ae_runtime_job` and `ae_runtime_job_attempt` identities.
- Implement only `START_EXECUTION` and `CONTINUE_EXECUTION` in P4.
- Keep a technical retry inside the same RuntimeJob and AgentExecution.
- Record every lease as an immutable attempt and reject stale workers.
- Keep raw prompts and responses outside RuntimeJob payload metadata.

## Decisions

- `execution_id` is the canonical AgentExecutionId and is not a CX JobId.
- `(tenant_id, dedup_key)` is unique. Reuse with different semantics fails.
- PostgreSQL claim uses `FOR UPDATE SKIP LOCKED`; SQLite regression uses the
  same guarded compare-and-update transition without PostgreSQL lock syntax.
- An expired lease closes its running attempt as `LEASE_EXPIRED` before the
  next worker creates a new attempt.
- Exhausted retry budget ends in `DEAD_LETTER`; non-retry failure ends in
  `FAILED`.

## Deferred

- ExecutableStep invocation and exactly-once Chat/RAG compatibility execution
  are P4-S6.
- Result persistence and publication delivery are P4-S7.
- Protected PostgreSQL restart and lease smoke evidence is P4-S8.

## Verification

- Focused regression: `21 passed`.
- RuntimeJob module coverage: `100%` statement, `100%` branch.
- Fifth-Slice Checkpoint Gate: `13,054 passed`, `32` protected skips.
- Checkpoint coverage: `98.98%` statement, `97.53%` branch.
- Contract validation: `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents passed.
