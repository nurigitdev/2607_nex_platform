# Slice 0609: AG worker execution PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL smoke evidence for the Slice 0608 AG worker execution
route.

## Decision

- No new database table is introduced in Slice 0609.
- The smoke uses the existing short AE persistence tables:
  `ae_daemon_operator_control_execution_states` and
  `ae_daemon_operator_control_execution_transitions`.
- AG remains read/projection-only. The AG route delegates to the AE worker route
  and must not write AE execution rows, enqueue jobs, or control processes.
- The worker route reads one persisted AE execution state, returns a fake
  dry-run worker result, and does not persist a transition row by itself.

## Implementation

- Added protected smoke runner
  `scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py`.
- Added the runner to `scripts/quality/run_quality_gate.sh`, defaulting to
  explicit opt-in skip behavior.
- The live smoke path runs AE migrations, persists one execution state in the
  AE test DB, calls the AG worker route, verifies that AG receives the result
  through AE's worker route, checks table/index/state JSONB evidence, and cleans
  up the targeted row.
- Added SQLite regression coverage for skip/fail/pass/redaction/helper/main
  branches.

## Guardrails

- Smoke execution requires
  `NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE=1`.
- The database URL must come from `NEX_AE_TEST_DATABASE_URL` and target a
  `_test` database.
- AG may call AE's protected worker route but must not persist transition rows,
  process rows, supervisor rows, worker-result rows, raw worker commands, raw
  supervisor results, storage paths, DB URLs, or provider credentials.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py
./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py -q --cov=run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test PYTHONPATH=scripts/smoke:services/_shared:services/nex-ae-api:services/nex-ag:scripts/db ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```

- Targeted regression: `15 passed`.
- Targeted smoke coverage: `100%`.
- PostgreSQL smoke: `pass`, `ag_worker=200`, `ae_worker=[200]`,
  `worker=SUCCEEDED`, `states=1`, `transitions=0`, `cleanup_states=1`,
  `cleanup_transitions=0`, and `live_db=true`.

## Next

- Slice 0610 should close S61 with a quality-gate checkpoint over the AE-owned
  worker execution surface and AG read/projection posture.
