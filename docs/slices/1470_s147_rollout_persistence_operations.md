# Slice 1470: S147 Rollout Persistence and Operations

## Outcome

- Added concise `mo_model_rollouts` and append-only `mo_rollout_events`
  tables with immutable revision identity, optimistic state revision, exact
  last-known-good lineage, evidence digests, and operations indexes.
- Added memory and SQLAlchemy repositories that atomically persist each state
  transition with its event and reject stale revision, identity, lineage, or
  event drift.
- Added memory/PostgreSQL runtime selection and restart-safe readback.
- Added NeX-AG-only read endpoints for rollout collections, details, and event
  history. Mutation remains internal to guarded orchestration.
- Kept operations projections metadata-only; model names, provider endpoints,
  credentials, prompts, vectors, and response payloads are excluded.

The same immutable model revision may have multiple rollout attempts, each
identified by a distinct `rollout_id`. Identity is indexed for correlation but
not globally unique, so a corrected calibration can be rehearsed after a
blocked or rolled-back attempt.

Slice 1471 executes the protected `nex_mo_test` migration/restart rehearsal and
non-disruptive live DGX/provider observation. It must not mutate a live alias or
provider process.

## Verification

- Contract validation passed for `166` schemas, `228` examples, `196` negative
  examples, and `7` OpenAPI documents.
- Affected MO contract/runtime parity regressions passed: `68 passed`.
- MO Slice Gate passed: `1,231 passed`, `6 skipped`, statement coverage
  `99.87%`, and branch coverage `99.39%`.
- Each of the six new persistence, repository, service, runtime, API, and smoke
  scopes reached statement/branch coverage `100.00%`.
- Deterministic restart/API smoke passed all `13/13` checks with zero residue.
