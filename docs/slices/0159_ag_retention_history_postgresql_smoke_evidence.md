# Slice 0159: AG Retention History PostgreSQL Smoke Evidence

## Scope

Slice 0159 hardens the existing AG-to-service PostgreSQL retention smoke so it
also proves that retention execution history is written by the target service
and readable through the AG operations projection.

Implemented:

- AG PostgreSQL retention smoke now injects the target service log store into
  the AG history projection path
- dispatch smoke verifies `GET /admin/v1/operations/logs/retention/history`
- evidence includes history projection schema, HTTP status, history count, and
  deleted-count summary
- cleanup removes smoke history rows by unique request ID

## Smoke Flow Addendum

After AG dispatches dry-run and guarded execute requests to the service-local
retention API, the smoke queries AG retention history with the same request ID.

Expected history:

- dry-run service execution
- guarded execute service execution
- no service history for the unsafe execute blocked by AG before dispatch

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py -k "ag_service_log_retention_postgres"
```

Default skipped smoke:

```bash
./.venv/bin/python scripts/smoke/run_ag_service_log_retention_postgres_smoke.py --summary
```

PostgreSQL test DB smoke evidence shape:

```text
ag_service_log_retention_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL audit_events=3 service_calls=2 deleted=1 history=2
```
