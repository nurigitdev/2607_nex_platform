# Slice 0880: S88 AG resilience and performance closure

## Goal

Close S88 by proving the performance policy, pagination, concurrency, source
isolation, pool operations, indexes, contracts, PostgreSQL load, privacy, and
operator runbook as one coherent NeX-AG capability.

## Closed Boundary

- Owner: NeX-AG admin-read and audit-evidence operations.
- Policy: validated page, admission, source timeout, pool, and p95 budgets.
- Pagination: opaque keyset cursor ordered by timestamp and stable identity.
- Concurrency: bounded process-local admission with retryable 503 shedding.
- Failure isolation: independent source timeout/failure counters and partial
  degraded projections without raw exception exposure.
- Database: separate API/worker SQLAlchemy pools and three short deterministic
  read indexes over existing `service_operational_events` and `ag_ev_exports`.
- Operations: protected resilience projection available during normal admission
  saturation.
- Contract: strict JSON Schema, OpenAPI, positive example, and negative database
  URL leak fixture.
- PostgreSQL: actual `nex_ag_test` migration, 25 requests at concurrency four,
  stable pagination, p95 measurement, planner-visible indexes, and zero residue.
- Runbook: normalized actions for admission, timeout, source, pool, latency,
  migration/index, pagination, connectivity, and cleanup failures.

No new table was introduced. S89 retains ownership of retention, archive, and
physical purge; S90 retains AG MVP acceptance and the CX transition checkpoint.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s88_ag_resilience_performance_closure.py \
  --cov=run_s88_ag_resilience_performance_closure \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_s88_ag_resilience_performance_closure.py --summary

NEX_AG_RESILIENCE_PERFORMANCE_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='<protected nex_ag_test URL>' \
./.venv/bin/python \
  scripts/smoke/run_s88_ag_resilience_performance_closure.py --summary
```

Observed verification:

```text
focused closure tests: 11 passed
closure runner statement/branch: 100%
protected default: PASS, contracts=PASS, postgres=SKIPPED, privacy=PASS
actual opt-in: PASS, contracts=PASS, postgres=PASS, privacy=PASS
contract validation: schemas=80 examples=130 negative_fixtures=93 openapi=7
direct SQL: database=nex_ag_test migration_present=true indexes=3
direct SQL: event_residue=0 export_residue=0
aggregate regression: 6011 passed, 1 known warning
statement=73675/74556=98.818337893664%
branch=17232/17882=96.365059836707%
```
