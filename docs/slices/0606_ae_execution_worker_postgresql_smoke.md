# Slice 0606: AE execution worker PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE operator-control execution
worker route introduced in Slice 0605.

## Decision

- No new database table is introduced in Slice 0606.
- The smoke uses the existing short persistence tables:
  `ae_daemon_operator_control_execution_states` and
  `ae_daemon_operator_control_execution_transitions`.
- The returned execution/transition contracts still report
  `database_write_performed=false`; actual persistence is proven by scoped row
  counts in the smoke evidence.
- The worker result remains non-persistent and fake dry-run only.

## Implementation

- Added protected smoke runner
  `scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py`.
- Added the runner to `scripts/quality/run_quality_gate.sh`, defaulting to
  explicit opt-in skip behavior.
- The live smoke path runs AE migrations, persists one execution state, calls
  the worker route by `operator_control_execution_state_id`, persists one
  transition, reads detail through AE API, validates table/index/JSONB evidence,
  and cleans up the targeted rows.
- Added SQLite regression coverage for skip/fail/pass/redaction/helper/main
  branches.

## Guardrails

- Smoke execution requires
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE=1`.
- The database URL must come from `NEX_AE_TEST_DATABASE_URL` and target a
  `_test` database.
- The worker route may invoke only the fake supervisor adapter. It must not add
  process rows, supervisor rows, JobQueue rows, persisted worker-result rows, or
  physical deletion evidence.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py tests/test_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py
./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py -q --cov=run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test PYTHONPATH=scripts/smoke:services/_shared:services/nex-ae-api:scripts/db ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```

- Targeted regression: `18 passed`.
- Targeted smoke coverage: `98%`.
- PostgreSQL smoke: `pass`, `routes=4`, `worker=SUCCEEDED`, `states=1`,
  `transitions=1`, `cleanup_states=1`, `cleanup_transitions=1`, `live_db=true`.
- Full regression/quality gate: `4269 passed`, statement coverage `98.56%`,
  branch coverage `95.68%`.

## Next

- Slice 0607 can add an AG-side worker diagnostics projection or continue
  toward worker transition persistence/read-model hardening, while keeping
  execution ownership inside AE.
