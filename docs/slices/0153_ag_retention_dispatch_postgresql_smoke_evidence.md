# Slice 0153: AG Retention Dispatch PostgreSQL Smoke Evidence

## Scope

Slice 0153 proves the AG operator-facing retention dispatch path against a
PostgreSQL-backed target service log store.

Implemented:

- `scripts/smoke/run_ag_service_log_retention_postgres_smoke.py`
- `NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE`
- `NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE_SERVICE`
- `NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE_PROFILE`
- default quality gate skipped summary
- `ag_service_log_retention_postgres` stage integration in
  `run_postgres_test_smoke_suite.py`

## Smoke Flow

When enabled, the standalone smoke uses the selected target service test
database and runs:

```text
apply target service migrations
build PostgreSQL-backed SqlAlchemyServiceLogStore
seed two very old smoke logs and one fresh smoke log
build target service app with service-local retention API
build AG app with local retention dispatch client
dispatch dry-run through AG and verify target service candidate count
submit unsafe execute through AG and verify AG blocks before service call
dispatch guarded execute through AG and verify one row is deleted
verify AG audit events for success, failure, success
cleanup temporary smoke rows
```

The smoke intentionally seeds rows before a `1970-01-03T00:00:00Z` cutoff so it
does not compete with normal recent test data.

## Safety Boundary

Default behavior is skipped:

```text
ag_service_log_retention_postgres_smoke=skipped reason=NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE
```

Live execution must explicitly enable the smoke and use the `test` profile:

```bash
NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE=1 \
NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE_SERVICE=nex-cx \
NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_ag_service_log_retention_postgres_smoke.py --summary
```

The broader PostgreSQL test smoke suite now includes this stage after the
service-local retention HTTP smoke when `NEX_POSTGRES_TEST_SMOKE_SUITE=1`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py
```

Default skipped smoke:

```bash
./.venv/bin/python scripts/smoke/run_ag_service_log_retention_postgres_smoke.py --summary
```

PostgreSQL test DB smoke evidence shape:

```text
ag_service_log_retention_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL audit_events=3 service_calls=2 deleted=1 history=2
```
