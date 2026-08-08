# Slice 0152: Service Log Retention HTTP PostgreSQL Smoke Evidence

## Scope

Slice 0152 proves that the service-local retention control API reaches a
PostgreSQL-backed `SqlAlchemyServiceLogStore`.

Implemented:

- `scripts/smoke/run_postgres_service_log_retention_http_smoke.py`
- `NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE`
- `NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE_SERVICE`
- `NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE_PROFILE`
- default quality gate skipped summary
- `service_log_retention_http` stage integration in
  `run_postgres_test_smoke_suite.py`

## Smoke Flow

When enabled, the standalone smoke uses the selected service test database and
runs the actual FastAPI route:

```text
apply service migrations
build SqlAlchemyServiceLogStore
seed two old smoke logs and one fresh smoke log
build service-local app with POST /internal/v1/service-logs/retention/purge
verify missing Authorization is rejected
verify dry_run=true plus delete_enabled=true is rejected
verify dry-run returns service_log_retention_execution.v1 and deletes nothing
verify execute without delete_enabled returns BLOCKED evidence
verify execute with delete_enabled=true deletes one old row
cleanup temporary smoke rows
```

This is intentionally separate from Slice 0151: Slice 0151 validates the store
adapter directly, while this slice validates the HTTP boundary, auth guard, and
payload validation in front of the same PostgreSQL store.

## Safety Boundary

Default behavior is skipped:

```text
postgres_service_log_retention_http_smoke=skipped reason=NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE
```

Live execution must explicitly enable the smoke and use the `test` profile:

```bash
NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE=1 \
NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE_SERVICE=nex-cx \
NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_postgres_service_log_retention_http_smoke.py --summary
```

The broader PostgreSQL test smoke suite now includes this stage after the direct
ServiceLog retention store smoke when `NEX_POSTGRES_TEST_SMOKE_SUITE=1`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py
```

Default skipped smoke:

```bash
./.venv/bin/python scripts/smoke/run_postgres_service_log_retention_http_smoke.py --summary
```

PostgreSQL test DB smoke evidence shape:

```text
postgres_service_log_retention_http_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL deleted=1
```
