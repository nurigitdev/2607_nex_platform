# P4-S8 Agent Runtime Observability and PostgreSQL Smoke

## Scope

- Wire the P4 Agent Runtime Foundation into AE startup without adding a public
  API or changing authenticated Chat/RAG behavior.
- Project a content-free diagnostic chain from trusted persistent identities:
  Interaction, trigger, IA, execution, job, compatibility step, existing
  retrieval/generation references, AgentResult, and ResultDelivery.
- Add an opt-in protected smoke against the real `nex_ae_test` database.
- Verify migration currency, restart restoration, lease recovery, idempotency,
  privacy, project neutrality, excluded WC scope, and cleanup.

## Decisions

- The runtime foundation shares the existing `ChatApplicationService`; it does
  not add a second invocation path.
- Startup is fail-closed only in `required` mode. `disabled` and `shadow` retain
  the approved compatibility behavior when canonical persistence is absent.
- Diagnostic output contains identifiers, hashes, states, counters, and safe
  references only. Prompt, response, evidence, and private document content are
  never copied into runtime metadata.
- The protected smoke uses a deterministic terminal compatibility result and
  does not contact remote embedding, reranking, or generation providers.
- The smoke target guard accepts only role `nex_ae_user` and database
  `nex_ae_test`; credentials are redacted from evidence.

## PostgreSQL Findings

- PostgreSQL returned `TIMESTAMPTZ` values in the session timezone while SQLite
  retained submitted strings. Runtime-job idempotency now compares parsed
  instants rather than timestamp spellings.
- A parameter inside the ExecutableStep completion `CASE` expression was
  inferred as text by PostgreSQL. The PostgreSQL statement now casts that
  parameter to `TIMESTAMPTZ`; the SQLite statement remains unchanged.
- Persisted result and delivery timestamps are normalized to UTC `Z`, so an
  identical retry returns the same semantic aggregate across both dialects.

## Live Evidence

- Target identity: database `nex_ae_test`, role `nex_ae_user`.
- Migration state: `31` planned, `31` already applied/skipped, latest
  `2006_ae_agent_result`.
- Checks: `14/14` passed.
- Persisted rows before cleanup: identity `1`, assignment `1`, conversation
  `1`, execution `2`, job `2`, attempt `3`, step `2`, result `1`, delivery `1`.
- Restart reconstruction restored the full trace; an expired lease was recorded
  and reclaimed by a newly constructed queue.
- Success-capable result remained `RUNNING / RESULT_PUBLISH` with required
  `WORKSPACE_RESULT` delivery `PENDING`; no false `SUCCEEDED` occurred.
- Cleanup residue: `0` rows for the smoke tenant and workspace.

## Verification

- ExecutableStep regression: `35 passed`, module statement/branch `100%`.
- Focused P4 runtime regression: `119 passed`; AgentResult,
  AgentRuntimeFoundation, ExecutableStep, and RuntimeJob modules achieved
  statement/branch `100%`.
- Protected PostgreSQL smoke: `PASS`, actual PostgreSQL, no skip.
- AE Slice Gate: `3,112 passed`, `5` unrelated protected PostgreSQL smoke
  skips; statement `98.43%`, branch `96.41%`.
- Contract validation: `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents passed.

## Deferred

- Publication preflight, `PUBLISH_RESULT`, ACK, retry/reconciliation, and final
  successful execution transition remain outside P4.
- Full Gate, existing Playwright journey, Frozen/amendment integrity, and final
  closure evidence belong to P4-S9.
