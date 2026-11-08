# P5-S7 Step Executors

## Scope

- Execute the existing P4 Chat/RAG path through a compatibility executor.
- Preserve asynchronous `PENDING -> WAITING -> CONTINUE_EXECUTION` behavior.
- Execute report and aggregate steps as deterministic projections over prior
  immutable StepResults.
- Dispatch executor kinds through one fail-closed registry and worker.

P5-S7 does not perform plan-level result verification, AgentResult synthesis,
or workspace publication. Those remain P5-S8 responsibilities.

## Compatibility Executor

- A fresh compatibility step invokes `ChatApplicationService.create` exactly
  once.
- A `PENDING` Chat/RAG response persists the step as `WAITING` with CX
  retrieval, generation, and job references; it does not create a StepResult.
- The continuation RuntimeJob contains references only. Its terminal result is
  consumed without invoking Chat/RAG again.
- Interaction lineage must match the compiled step. Unsupported status,
  malformed response, mismatched lineage, and a second pending response fail
  closed.
- StepResult payloads retain identifiers and references only; prompt and model
  response content are not duplicated.

## Deterministic Projection

- `DETERMINISTIC_REPORT` and `DETERMINISTIC_AGGREGATE` accept successful prior
  StepResults only.
- `COMPILED_STEP_OUTPUT`, `LITERAL`, and `RESOURCE_REF` bindings are resolved
  from the compiled plan without an LLM call.
- Output provenance includes the source StepResult reference, semantic result
  hash, and result contract.
- External, artifact, and evidence references are sorted and deduplicated.
- Missing dependencies, duplicate targets, malformed arrays, and unsupported
  binding types fail closed.

## Worker And Recovery

- The worker begins the claimed step through the S6 multi-step engine, then
  dispatches only the exact compiled executor kind.
- Terminal executor errors become immutable failed StepResults and failed
  RuntimeJobs with bounded error codes; callback details are not persisted.
- A job recovered after its StepResult was committed completes without
  executing the adapter again.
- WAITING is an active step state, so ordinary scheduling cannot create a
  parallel job. Only a lineage-matched `CONTINUE_EXECUTION` may resume it.

## Verification

- Focused tests passed `51/51`, covering synchronous and asynchronous
  compatibility paths, deterministic report/aggregate projection, restart
  no-reexecution, protected-smoke contracts, and all new fail-closed branches.
- `nex_ae_api.multi_step_engine` and `nex_ae_api.step_executors` each reached
  `100%` statement and `100%` branch coverage in focused and Slice Gate tests.
- Protected PostgreSQL smoke connected as `nex_ae_user@nex_ae_test`, verified
  the complete `38`-migration inventory, and passed `20/20` checks. It executed
  WAITING/CONTINUE and report projection, verified one Chat/RAG invocation,
  two StepResults, three RuntimeJobs/attempts, restart safety, and zero tenant
  residue.
- Remote providers are not required: the compatibility callback is a bounded
  deterministic test double while the database and runtime queue are real.
- AE Slice Gate passed with `3461 passed`, `5` protected opt-in tests skipped;
  statement coverage `98.60%`, branch coverage `96.80%`.
- Contract validation passed `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents.

## Deferred

- P5-S8 owns required StepResult verification, AgentResult synthesis, and
  `PENDING / WORKSPACE_RESULT` delivery creation.
- P5-S9 owns the full P5 regression and closure audit.
