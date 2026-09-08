# Slice 0586: AE operator-control PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE-owned scheduler daemon
operator-control facade.

## Implementation

- Added
  `scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py`.
- The smoke is skipped by default in the quality gate until explicitly enabled
  with `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE=1`.
- When enabled, it requires `NEX_AE_TEST_DATABASE_URL`, enforces the `test`
  profile, applies AE migrations to the real test DB, attaches a PostgreSQL
  session factory to the AE TestClient app, and calls:
  `/api/v1/artifact-retention/scheduler-daemon-operator-control-policy` and
  `/api/v1/artifact-retention/scheduler-daemon-operator-control-preview`.
- The DB evidence checks `SELECT 1`, migration marker presence, supervised
  process table/index presence, and before/after supervised-process row counts.
- Added SQLite-backed regression coverage for skip, profile guard, missing DB
  URL, migration failure redaction, successful smoke shape, failed checks, route
  setup failure, and explicit redaction guards.
- Added the runner to `scripts/quality/run_quality_gate.sh`.

## Guardrails

- The smoke does not start, stop, restart, or dispatch a scheduler daemon.
- The preview route does not invoke the supervisor adapter.
- The preview route does not write DB rows or enqueue the JobQueue.
- The PostgreSQL check verifies row counts are unchanged before and after route
  calls.
- Evidence redacts database URLs, passwords, local storage paths, and provider
  API keys.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py tests/test_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py
PYTHONPATH=services/_shared:services/nex-ae-api:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py -q
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE=1 ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```

PostgreSQL smoke result:

```text
ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL routes=3 preview_only=true unchanged=true live_db=true
```

Quality gate result: `3965 passed`, statement coverage `98.58%`, branch
coverage `95.76%`.

## Next

- Slice 0587 can project the protected operator-control facade into AG
  operations without giving AG process-control ownership.
