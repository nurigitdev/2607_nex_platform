# Slice 0578: AG supervised process PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE-owned supervised process
snapshot tables read through AG's admin projection routes.

## Implementation

- Added
  `scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py`.
- The smoke is skipped by default and requires
  `NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_READ_MODEL_POSTGRES_SMOKE=1`.
- The smoke requires `NEX_AE_TEST_DATABASE_URL`, rejects non-test profiles, runs
  AE migrations, writes process snapshot evidence through AE APIs, and reads the
  same evidence back through AG admin routes.
- Added regression coverage for skip behavior, profile/database guardrails,
  redaction, SQLite harness pass, failed-check handling, cleanup verification,
  bridge helpers, and CLI summary output.
- Added the protected smoke hook to `scripts/quality/run_quality_gate.sh`.

## Smoke Flow

When enabled, the smoke:

- creates one `status_probe`/`MISSING` supervised process snapshot through AE,
- creates one `start_daemon`/`RUNNING` supervised process snapshot through AE,
- verifies direct PostgreSQL row counts, scheduler/action/status counts, pid
  lookup, migration marker, tables, indexes, and JSONB column types,
- reads the `RUNNING` process through AG's collection and detail routes,
- verifies AG projection schema versions, read-only guidance, source status,
  summary counts, and detail event evidence,
- deletes inserted process snapshot/event rows and verifies cleanup.

## Guardrails

- The smoke writes only to the AE test database.
- AG reads through AE APIs and does not connect directly to AE persistence.
- AG still cannot start/stop subprocesses, enqueue AE jobs, write AE tables, or
  receive raw process/runtime payloads.
- Evidence redacts database URLs, passwords, storage paths, artifact payloads,
  execution payloads, and daemon runtime payloads.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py tests/test_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py
PYTHONPATH=services/_shared:services/nex-ae-api:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py -q --cov=run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_READ_MODEL_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py --summary
```

Targeted smoke regression: 10 passed, script coverage 97%.

Live test database smoke:

```text
ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke=pass service=nex-ae-api ag_service=nex-ag db_env=NEX_AE_TEST_DATABASE_URL db_records=2 events=2 running=RUNNING ag_collection=200 ag_detail=200 live_db=true cleanup_records=2
```

## Next

- Slice 0579 should add the supervised process read model to the AG operations
  dashboard smoke/operator surface.
