# P4-S7 AgentResult and Pending ResultDelivery

## Scope

- Close `P4-ISSUE-026` from cited Frozen state-machine and result-publication
  semantics before implementing non-success state transitions.
- Persist one complete immutable Frozen AgentResult per AgentExecution.
- Atomically create exactly one required `WORKSPACE_RESULT` ResultDelivery in
  `PENDING` state.
- Persist deterministic result hash and Frozen publication operation identities.
- Preserve only legacy Chat/RAG references and hashes in the canonical result.

## Decisions

- `SUCCEEDED` and `PARTIAL` AgentResult statuses leave AgentExecution at
  `RUNNING / RESULT_PUBLISH` until a later phase obtains required delivery ACK.
- `BLOCKED`, `FAILED`, and `CANCELLED` transition directly to the matching
  terminal execution state with `FINALIZE` and `completed_at`.
- Legacy `COMPLETED` maps to `PARTIAL` when the existing grounded-response or
  retrieval quality projection contains a real degradation signal.
- `(tenant_id, agent_execution_id)` is unique. An identical retry returns the
  existing aggregate; a changed result identity or semantic hash conflicts.
- AgentResult, PENDING delivery, and AgentExecution transition use one AE-local
  transaction. Any delivery or execution write failure rolls the result back.
- P4 creates no `PUBLISH_RESULT` job, preflight, ACK, WC delivery, optional
  fan-out, or generation replay.

## Verification

- Focused regression: `49 passed`.
- AgentResult module coverage: `100%` statement, `100%` branch.
- Adjacent P4 S3-S7 regression: `117 passed`.
- AE Slice Gate: `3,097 passed`, `5` protected PostgreSQL smoke skips.
- AE coverage: `98.43%` statement, `96.40%` branch.
- Contract validation: `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents passed.

## Deferred

- Route/startup wiring and protected PostgreSQL migration/restart evidence are
  P4-S8.
- Publication preflight, delivery execution, ACK, retry/reconciliation, and
  successful AgentExecution finalization remain outside P4.
