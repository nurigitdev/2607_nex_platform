# Slice 0566: AE daemon supervisor PostgreSQL smoke evidence

## Scope

Prove the AE scheduler daemon supervisor API path against the real AE test
database boundary.

## Implementation

- Added
  `scripts/smoke/run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke.py`.
- Added
  `database/nex-ae-api/migrations/0566_ae_artifact_retention_scheduler_daemon_supervisor_index_names.sql`
  so PostgreSQL uses short canonical supervisor index names instead of
  truncated long identifiers.
- The protected smoke requires
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_POSTGRES_SMOKE=1`.
- The smoke only accepts the `test` profile and
  `NEX_AE_TEST_DATABASE_URL`.
- It runs AE migrations before dispatching supervisor API calls.
- It calls the AE supervisor API for `status_probe` and guarded
  `start_daemon`, then reads the blocked start result through collection and
  detail routes.
- It directly verifies supervisor result/event rows, indexes, JSONB columns on
  PostgreSQL, migration recording, and cleanup.
- Runtime schema creation now uses the same short index names as the 0566
  migration.

## Guardrails

- Default quality-gate behavior remains skipped until explicitly enabled.
- `start_daemon` remains fake/dry-run and blocked; no OS process is started.
- No JobQueue retention work, worker execution, physical purge, raw database
  URL, local storage path, or secret is emitted in smoke evidence.
- Cleanup removes the inserted supervisor records/events and verifies zero
  remaining smoke rows.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke.py tests/test_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke.py
PYTHONPATH=services/_shared:services/nex-ae-api:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke.py -q --cov=run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```

Results:

- Targeted smoke regression: `14 passed`; smoke script coverage `99%`.
- Protected PostgreSQL smoke:
  `ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL dispatches=2 records=2 events=2 start=BLOCKED cleanup_records=2 live_db=true`.
- Full quality gate: `3712 passed`, statement coverage `98.61%`, branch
  coverage `95.95%`, contract validation pass.
- Default protected smoke state:
  `ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke=skipped reason=NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_POSTGRES_SMOKE`.

## Next

- Slice 0567 should add the AG read-only supervisor projection over AE-owned
  supervisor APIs.
