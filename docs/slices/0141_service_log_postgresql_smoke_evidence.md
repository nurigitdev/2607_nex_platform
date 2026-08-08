# Slice 0141: Service Log PostgreSQL Smoke Evidence

## Scope

Slice 0141 adds guarded PostgreSQL test-profile smoke evidence for the
service-local structured log store introduced in Slices 0136-0140.

Implemented:

- `scripts/smoke/run_postgres_service_log_smoke.py`
- `NEX_DB_SERVICE_LOG_SMOKE`
- `NEX_DB_SERVICE_LOG_SMOKE_SERVICE`
- `NEX_DB_SERVICE_LOG_SMOKE_PROFILE`
- default quality gate skipped summary
- service log stage integration in `run_postgres_test_smoke_suite.py`
- service log subsmoke integration in `run_postgres_operations_smoke_pack.py`

## Smoke Flow

When enabled, the standalone smoke uses the selected service test database and
runs:

```text
apply service migrations
build SqlAlchemyServiceLogStore
append redaction-safe ERROR log
append duplicate log_id with changed severity
read back log by id
filter by service/severity/logger/trace/request/job/subject
verify summary counts
cleanup temporary smoke rows
```

The smoke validates that direct sensitive attributes are omitted, nested
sensitive attributes are redacted, and evidence never includes database
credentials or private attribute values.

## Safety Boundary

Default behavior is skipped:

```text
postgres_service_log_smoke=skipped reason=NEX_DB_SERVICE_LOG_SMOKE
```

Live execution must explicitly enable the smoke and use the `test` profile:

```bash
NEX_DB_SERVICE_LOG_SMOKE=1 \
NEX_DB_SERVICE_LOG_SMOKE_SERVICE=nex-cx \
NEX_DB_SERVICE_LOG_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_postgres_service_log_smoke.py --summary
```

The broader PostgreSQL test smoke suite now includes this stage when
`NEX_POSTGRES_TEST_SMOKE_SUITE=1`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_nex_runtime_service_logs.py
```

Default skipped smoke:

```bash
./.venv/bin/python scripts/smoke/run_postgres_service_log_smoke.py --summary
```

PostgreSQL test DB smoke evidence:

```text
postgres_service_log_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
```
