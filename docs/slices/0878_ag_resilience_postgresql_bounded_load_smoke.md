# Slice 0878: AG resilience PostgreSQL bounded-load smoke

## Goal

Prove the S88 contract against the actual `nex_ag_test` PostgreSQL database,
including migrations, indexes, concurrent reads, latency budget, and cleanup.

## Implementation

- Added an opt-in smoke runner that applies all NeX-AG test migrations before
  opening separate API and worker SQLAlchemy engines with their configured pools.
- Inserts 25 owned audit events and four evidence exports, then issues 25
  protected operations requests with concurrency four.
- Measures nearest-rank p50, p95, and maximum latency against the configured
  1,500 ms p95 budget.
- Verifies stable first-page signatures, disjoint cursor pages, no admission
  rejection, and no source timeout or failure.
- Reads `pg_indexes`, forces local index plans for three bounded queries, and
  verifies migration `0877_ag_resilience_read_indexes` in `schema_migrations`.
- Deletes only the smoke-owned trace rows and requires exact delete counts and
  zero remaining rows.
- The non-opt-in path reports `SKIPPED`; live evidence must report `PASS` and is
  never inferred from a skipped run.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_ag_resilience_performance_postgres_smoke.py \
  --cov=run_ag_resilience_performance_postgres_smoke \
  --cov-branch --cov-report=term-missing

NEX_AG_RESILIENCE_PERFORMANCE_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='<protected nex_ag_test URL>' \
./.venv/bin/python \
  scripts/smoke/run_ag_resilience_performance_postgres_smoke.py --summary
```

Observed verification:

```text
focused smoke runner tests: 11 passed
smoke runner statement/branch: 100%
live smoke: PASS
database=nex_ag_test backend=postgresql requests=25 concurrency=4
p95_ms=49.678 budget_ms=1500 indexes=3 cleaned=True
direct SQL: migration_present=true indexes=3 event_residue=0 export_residue=0
aggregate regression: 5992 passed, 1 known warning
statement=73436/74317=98.814537723536%
branch=17214/17864=96.361397223466%
```
