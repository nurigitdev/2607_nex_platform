# P4-S6 ExecutableStep and Chat/RAG Adapter

## Scope

- Persist one canonical compatibility ExecutableStep per AgentExecution.
- Reuse Frozen ExecutableStep state vocabulary.
- Delegate to the extracted v1 Chat/RAG application service exactly once.
- Preserve legacy interaction, retrieval, CX generation/job, generated
  response, result, error, correlation, and causation references.
- Continue asynchronous terminalization with a unique `CONTINUE_EXECUTION`
  RuntimeJob and no generation replay.

## Decisions

- `P4_CHAT_RAG_COMPATIBILITY` is transition metadata, not a new Frozen
  business step taxonomy or an NSL Skill.
- The durable `READY -> RUNNING` CAS occurs before the legacy callback starts.
  A reclaimed job cannot call an already-started compatibility step again.
- A synchronous terminal result finishes the step. An asynchronous admission
  records `WAITING`; only an authoritative terminal projection may enqueue and
  run a continuation.
- The step stores references and hashes only. Raw prompt and generated response
  content remain in their existing owner-private stores.
- Shadow fallback is available only while the shared application invocation is
  still `READY`. A wrapper failure after invocation returns the valid legacy
  result without replaying Chat/RAG.

## Deferred

- AgentResult and required PENDING ResultDelivery are P4-S7.
- Route/startup wiring and protected PostgreSQL restart evidence are P4-S8.

## Verification

- Focused regression: `34 passed`.
- ExecutableStep module coverage: `100%` statement, `100%` branch.
- AE Slice Gate: `3,048 passed`, `5` protected skips.
- AE coverage: `98.40%` statement, `96.34%` branch.
- Contract validation: `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents passed.
