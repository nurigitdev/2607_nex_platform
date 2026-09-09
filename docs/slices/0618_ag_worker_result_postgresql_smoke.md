# Slice 0618: AG worker result PostgreSQL smoke evidence

## Scope

Add protected cross-service PostgreSQL smoke evidence for the persisted AE
operator-control execution worker-result read model exposed through AG.

## Decision

- No new database table is added in this slice.
- The existing short AE-owned table remains `ae_op_exec_worker_results`.
- AG remains a read-only operations facade and does not connect to the AE
  database directly.
- The smoke writes through protected AE routes, reads the same record through
  protected AE read-model routes, then verifies AG can project the collection
  and detail through its protected admin routes.
- The smoke is explicitly opt-in with
  `NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_READ_MODEL_POSTGRES_SMOKE=1`.
- The smoke is test-profile only and requires `NEX_AE_TEST_DATABASE_URL`.

## Implementation

- Added
  `scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py`.
- The smoke runs AE migrations, creates one persisted execution state, runs the
  AE worker route with `persist_worker_result=true`, reads AE worker-result
  collection/detail APIs, and reads the matching AG collection/detail admin
  projections.
- Evidence records route status, scoped PostgreSQL row counts, table/index
  presence, JSONB column verification, safe hash-presence indicators, redaction,
  and targeted cleanup.
- Added the smoke to `scripts/quality/run_quality_gate.sh`; it skips by default
  until explicitly enabled.
- Added regression coverage for skip/profile/URL guards, redaction, failure
  wrapping, SQLite-backed happy path, failed checks, cleanup verification, bridge
  error handling, helper behavior, and CLI output.

## Live Test DB Evidence

Executed against the real AE test database:

```bash
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' \
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_READ_MODEL_POSTGRES_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py --summary
```

Observed:

```text
ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke=pass service=nex-ae-api ag_service=nex-ag db_env=NEX_AE_TEST_DATABASE_URL results=1 states=1 ae_read=200/200 ag_read=200/200 worker=SUCCEEDED cleanup_results=1 cleanup_states=1 live_db=true
```

## Regression Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py
PYTHONPATH=services/_shared:services/nex-ae-api:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py -q
PYTHONPATH=services/_shared:services/nex-ae-api:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py -q --cov=run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

Observed targeted regression:

```text
11 passed, 1 warning
```

Observed targeted coverage:

```text
run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py: 99%
```

Observed quality gate:

```text
4377 passed, 1 warning
statement_coverage=98.57% threshold=95.00%
branch_coverage=95.69% threshold=85.00%
contract_validation=pass schemas=70 examples=101 negative_examples=75 openapi=7
```

## Next

- Slice 0619 should add an AG worker-result diagnostics rollup so operators can
  reason about worker execution and persisted worker-result evidence together.
