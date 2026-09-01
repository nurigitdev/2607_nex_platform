# Slice 0489: AE artifact retention scheduled execution PostgreSQL smoke

Add protected test-database evidence for the scheduled artifact retention
execution path.

## Changes

- Added
  `scripts/smoke/run_ae_artifact_retention_scheduled_execution_postgres_smoke.py`.
- The smoke migrates the AE test database, creates rendered logical-purge
  artifacts, reads the AE batch plan route, builds the scheduled execution
  command, runs the mock scheduled worker against SQLAlchemy artifact and
  history stores, and verifies the history row directly through the test DB
  store.
- The smoke also projects the live plan through AG's metadata-only batch
  operations projection to prove the AG operator view stays connected without
  direct AG writes into AE persistence.
- Added a pytest wrapper covering disabled skip, configuration failures,
  migration failures, SQLite regression harness success, failed checks,
  redaction helpers, and CLI summary output.
- Added the protected smoke to the default quality gate in skip-safe mode.

## Real Test DB Command

Run with the AE test database URL configured:

```bash
NEX_AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' \
./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduled_execution_postgres_smoke.py --summary
```

## Verification

- `./.venv/bin/pytest tests/test_ae_artifact_retention_scheduled_execution_postgres_smoke.py -q --cov=run_ae_artifact_retention_scheduled_execution_postgres_smoke --cov-branch --cov-report=term-missing`
- Protected PostgreSQL smoke against `NEX_AE_TEST_DATABASE_URL` when
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_POSTGRES_SMOKE=1`.
