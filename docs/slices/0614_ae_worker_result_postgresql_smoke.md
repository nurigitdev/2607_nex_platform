# Slice 0614: AE worker result PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE operator-control execution
worker result persistence path.

## Decision

- No new database table is added in this slice.
- The smoke uses the existing short `ae_op_exec_worker_results` table from
  Slice 0612.
- The smoke is explicitly opt-in with
  `NEX_AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE=1`.
- The smoke is test-profile only and requires `NEX_AE_TEST_DATABASE_URL`.
- The route writes remain explicit: one persisted execution state is created
  first, then the worker route writes a result only with
  `persist_worker_result=true`.
- Evidence must prove PostgreSQL dialect health, migration freshness, table and
  index presence, JSONB result summary columns, route upsert/select behavior,
  redaction, and scoped cleanup.

## Implementation

- Added
  `scripts/smoke/run_ae_operator_control_execution_worker_result_postgres_smoke.py`.
- Added regression coverage for default skip behavior, profile/URL guards,
  redaction, failure wrapping, route checks, scoped cleanup, and PostgreSQL
  helper probes.
- Added the protected smoke hook to `scripts/quality/run_quality_gate.sh`; it
  skips by default until the opt-in flag is set.

## Live Test DB Evidence

Executed against the real AE test database:

```bash
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' \
NEX_AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_ae_operator_control_execution_worker_result_postgres_smoke.py --summary
```

Observed:

```text
ae_operator_control_execution_worker_result_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL routes=2 worker=SUCCEEDED results=1 states=1 transitions=0 cleanup_results=1 cleanup_states=1 live_db=true
```

The smoke runs AE migrations, calls the protected execution and worker routes,
selects the persisted worker result through the SQLAlchemy store, verifies JSONB
column types on PostgreSQL, and deletes the targeted result/state rows.

## Regression Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_operator_control_execution_worker_result_postgres_smoke.py tests/test_ae_operator_control_execution_worker_result_postgres_smoke.py
PYTHONPATH=services/_shared:services/nex-ae-api:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ae_operator_control_execution_worker_result_postgres_smoke.py -q
./scripts/quality/run_quality_gate.sh
```

Observed targeted regression:

```text
17 passed, 1 warning
```

Observed quality gate:

```text
4355 passed, 1 warning
statement_coverage=98.58% threshold=95.00%
branch_coverage=95.73% threshold=85.00%
```

## Next

- Slice 0615 should expose a protected AE read-model route for persisted worker
  results so AG can later project them without direct AE database access.
