# Slice 0151: Service Log Retention PostgreSQL Smoke Evidence

## Scope

Slice 0151 adds guarded PostgreSQL test-profile smoke evidence for the
service-local structured log retention purge path.

Implemented:

- `scripts/smoke/run_postgres_service_log_retention_smoke.py`
- `NEX_DB_SERVICE_LOG_RETENTION_SMOKE`
- `NEX_DB_SERVICE_LOG_RETENTION_SMOKE_SERVICE`
- `NEX_DB_SERVICE_LOG_RETENTION_SMOKE_PROFILE`
- default quality gate skipped summary
- `service_log_retention` stage integration in
  `run_postgres_test_smoke_suite.py`

## Smoke Flow

When enabled, the standalone smoke uses the selected service test database and
runs:

```text
apply service migrations
build SqlAlchemyServiceLogStore
seed two old smoke logs and one fresh smoke log
run retention dry-run and verify no rows are deleted
run execute without delete_enabled and verify BLOCKED
run execute with delete_enabled=true and max_delete_count=1
verify only the oldest old row is deleted
cleanup temporary smoke rows
```

The smoke records redacted database connection evidence only and does not place
tokens, database passwords, or raw private attribute values into the evidence
payload.

## Safety Boundary

Default behavior is skipped:

```text
postgres_service_log_retention_smoke=skipped reason=NEX_DB_SERVICE_LOG_RETENTION_SMOKE
```

Live execution must explicitly enable the smoke and use the `test` profile:

```bash
NEX_DB_SERVICE_LOG_RETENTION_SMOKE=1 \
NEX_DB_SERVICE_LOG_RETENTION_SMOKE_SERVICE=nex-cx \
NEX_DB_SERVICE_LOG_RETENTION_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_postgres_service_log_retention_smoke.py --summary
```

The broader PostgreSQL test smoke suite now includes this stage after the
ServiceLogStore smoke when `NEX_POSTGRES_TEST_SMOKE_SUITE=1`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py
```

Default skipped smoke:

```bash
./.venv/bin/python scripts/smoke/run_postgres_service_log_retention_smoke.py --summary
```

PostgreSQL test DB smoke evidence shape:

```text
postgres_service_log_retention_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL deleted=1
```
