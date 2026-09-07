# Slice 0569: AG daemon supervisor PostgreSQL smoke evidence

## Scope

Prove the AG scheduler daemon supervisor read-model routes against AE-owned
PostgreSQL test storage.

## Implementation

- Added
  `scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervisor_read_model_postgres_smoke.py`.
- The protected smoke requires
  `NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_READ_MODEL_POSTGRES_SMOKE=1`.
- The smoke only accepts the `test` profile and
  `NEX_AE_TEST_DATABASE_URL`.
- It runs AE migrations, dispatches AE supervisor `status_probe` and guarded
  `start_daemon` requests, then reads the persisted supervisor result through
  AG admin collection/detail routes.
- It verifies AE supervisor result/event row counts, AG projection schema
  versions, source status, read-only operator guidance, and cleanup.
- Added the protected smoke to the default quality gate as a skipped-until-opted
  summary command.

## Guardrails

- AG reads through AE service APIs only.
- AE remains the system of record for supervisor persistence and daemon process
  ownership.
- The smoke keeps `start_daemon` fake/dry-run and blocked; no OS process is
  started.
- Raw supervisor command/result payloads, database URLs, local storage paths,
  raw artifact payloads, and raw execution payloads are not emitted in evidence.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervisor_read_model_postgres_smoke.py tests/test_ae_ag_artifact_retention_scheduler_daemon_supervisor_read_model_postgres_smoke.py
PYTHONPATH=services/_shared:services/nex-ae-api:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_supervisor_read_model_postgres_smoke.py -q --cov=run_ae_ag_artifact_retention_scheduler_daemon_supervisor_read_model_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_READ_MODEL_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervisor_read_model_postgres_smoke.py --summary
```

Results:

- Targeted smoke regression: `10 passed`; smoke script coverage `97%`.
- Protected PostgreSQL smoke:
  `ae_ag_artifact_retention_scheduler_daemon_supervisor_read_model_postgres_smoke=pass service=nex-ae-api ag_service=nex-ag db_env=NEX_AE_TEST_DATABASE_URL db_records=2 events=2 ag_collection=200 ag_detail=200 start=BLOCKED live_db=true cleanup_records=2`.

## Next

- Slice 0570 should close S57 by adding an S57 supervisor operations closure
  checkpoint to the quality gate.
