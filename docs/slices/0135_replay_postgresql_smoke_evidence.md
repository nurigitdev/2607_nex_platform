# Slice 0135: Replay PostgreSQL Smoke Evidence

## Scope

Slice 0135 adds guarded PostgreSQL smoke evidence for the dead-letter replay
path on the shared SQLAlchemy JobQueue adapter.

Implemented:

- `scripts/smoke/run_postgres_job_replay_smoke.py`
- `0135_service_job_replay_lineage.sql` for every service database
- SQLAlchemy `service_jobs.replay_lineage` JSONB persistence/readback
- guarded environment flag `NEX_DB_JOB_REPLAY_SMOKE`
- test-profile-only execution guard
- replay stage integration in `run_postgres_test_smoke_suite.py`
- default quality gate skipped summary for the standalone replay smoke

## Smoke Flow

When enabled, the smoke uses the selected service test database and runs:

```text
enqueue source job with payload
claim source job
retry source job into FAILED dead-letter state
plan_dead_letter_replay()
enqueue replay job
verify replay payload, lineage, idempotency, and readback
cleanup source/replay rows
```

The smoke defaults to `nex-cx` and `test`:

```bash
NEX_DB_JOB_REPLAY_SMOKE=1 \
NEX_DB_JOB_REPLAY_SMOKE_SERVICE=nex-cx \
NEX_DB_JOB_REPLAY_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_postgres_job_replay_smoke.py --summary
```

The broader PostgreSQL test smoke suite now includes this stage when
`NEX_POSTGRES_TEST_SMOKE_SUITE=1`.

## Evidence

Default skipped evidence remains part of the quality gate:

```text
postgres_job_replay_smoke=skipped reason=NEX_DB_JOB_REPLAY_SMOKE
```

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_jobs.py tests/test_smoke_helpers.py tests/test_db_migration_runner.py tests/test_database_schema_foundation.py
./.venv/bin/python scripts/smoke/run_postgres_job_replay_smoke.py --summary
```

PostgreSQL test DB smoke evidence:

```text
postgres_job_replay_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
```
