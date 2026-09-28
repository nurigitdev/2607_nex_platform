# Slice 1050: AE Generation Lifecycle PostgreSQL Smoke Evidence

## Goal

Prove S105 lifecycle orchestration against the actual `nex_ae_test` and
`nex_cx_test` PostgreSQL databases.

## Implementation

- Added a protected, opt-in two-database smoke runner.
- Runs current AE and CX migrations before executing the lifecycle flow.
- Exercises queued progress, completed-before-cancel race convergence, owner
  isolation, queued cancellation, recovery planning, child retry admission,
  lineage persistence, and retry progress.
- Uses the deterministic mock generation provider while persisting real CX
  jobs/executions and AE chat/event records.
- Reopens both databases through fresh engines to verify restart reads.
- Deletes all probe chat, render-event, operational-event, job, execution, and
  admission rows and asserts zero residue.

## Decisions

- Remote providers are outside S105 lifecycle orchestration and are not
  required for this smoke.
- The runner rejects non-test database names or unexpected database roles.
- Database URLs and passwords are redacted from evidence and failures.

## Verification

```bash
NEX_AE_GENERATION_LIFECYCLE_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/pytest -q tests/test_ae_generation_lifecycle_postgres_smoke.py
```

## Observed Evidence

- Slice Gate: `2326 passed`, `1 skipped` (the separately protected S104
  smoke), statement coverage `97.92%`, branch coverage `95.78%`.
- Smoke runner coverage: statement `100.00%`, branch `94.44%`.
- Contract validation: `100` schemas, `156` examples, `119` negative
  examples, and `7` OpenAPI documents.
- Actual PostgreSQL smoke: `23/23` checks passed against `nex_ae_test` and
  `nex_cx_test`; both migration chains were current.
- Probe rows covered three AE interactions, six AE lifecycle events, two CX
  executions, and three CX jobs; cleanup left `0/0` AE/CX rows.
- Remote providers were not required because S105 verifies lifecycle control
  orchestration with a deterministic generation provider.
