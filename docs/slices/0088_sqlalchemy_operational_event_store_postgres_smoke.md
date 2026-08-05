# Slice 0088: SQLAlchemy OperationalEventStore and PostgreSQL smoke

## Intent

Slice 0088 makes operational events durable without making the default
regression suite depend on PostgreSQL. It also documents the testing boundary:
SQLite regression covers fast behavioral feedback, while PostgreSQL smoke
checks canonical DDL and runtime semantics.

## Runtime Behavior

`nex_runtime.operational_events` now provides:

- `SqlAlchemyOperationalEventStore`
- persistent append/get/list/filter/summary over `service_operational_events`
- idempotent append by `event_id`
- redaction before persistence through the existing event builder
- PostgreSQL `JSONB` details storage
- SQLite-compatible JSON text fallback for regression tests

Returned events remain aligned to `operational_event.v1`.

## Testing Boundary

PostgreSQL migration SQL is canonical. SQLite DDL in tests is a behavioral
fixture only. It should not be treated as proof that PostgreSQL DDL, JSONB,
TIMESTAMPTZ, constraints, or lock behavior are equivalent.

The intended split is:

- SQLite regression: fast adapter behavior, filter semantics, summary shape,
  idempotency shape, and branch coverage.
- PostgreSQL smoke: migration compatibility, real JSONB storage, TIMESTAMPTZ
  round-trip, constraints, and service-owned test DB write safety.

## PostgreSQL Smoke

The optional smoke script is:

```bash
./.venv/bin/python scripts/smoke/run_postgres_operational_event_smoke.py --summary
```

Default behavior is skipped. To execute against a local test DB:

```text
NEX_DB_OPERATIONAL_EVENT_SMOKE=1
NEX_DB_OPERATIONAL_EVENT_SMOKE_SERVICE=nex-cx
NEX_DB_OPERATIONAL_EVENT_SMOKE_PROFILE=test
```

The smoke is write-capable but limited to the `test` profile. It applies
service migrations, appends one redaction-guarded event, validates idempotency,
checks list filters and summary output, and deletes the smoke row.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_operational_events.py tests/test_smoke_helpers.py`
- Optional PostgreSQL smoke:
  `NEX_DB_OPERATIONAL_EVENT_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_postgres_operational_event_smoke.py --summary`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
