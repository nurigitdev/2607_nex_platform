# Slice 0091: Service runtime persistence bootstrap

## Intent

Slice 0091 adds a common service runtime persistence bootstrap. This is the
switch that keeps default regression runs mock-first while allowing selected
services to use PostgreSQL-backed runtime stores when explicitly enabled.

## Why It Exists

The project now uses a deliberate testing split:

- SQLite regression for fast adapter behavior and branch coverage.
- Guarded PostgreSQL smoke for canonical DDL and runtime semantics.

Without a runtime bootstrap, service entrypoints would either stay permanently
in-memory or accidentally couple normal regression tests to PostgreSQL. The new
bootstrap makes that choice explicit through environment mode.

## Runtime Behavior

`nex_runtime.persistence` now provides:

- `build_service_persistence_runtime`
- `attach_service_persistence_runtime`
- `ServicePersistenceRuntime`
- `normalize_persistence_mode`

Supported modes:

- `memory`: default; uses `InMemoryJobQueue` and
  `InMemoryOperationalEventStore`.
- `postgres`: requires the service database URL; builds SQLAlchemy-backed
  JobQueue and OperationalEventStore using service-aware API/worker pool
  settings.

Mode env lookup is service-specific first, then global:

```text
NEX_CX_PERSISTENCE_MODE
NEX_PERSISTENCE_MODE
```

Every service entrypoint attaches the runtime to `app.state.nex_persistence`.
CX processing now receives the runtime JobQueue, so
`NEX_CX_PERSISTENCE_MODE=postgres` can switch the processing job lifecycle to
`service_jobs` without changing route code.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_persistence.py tests/test_nex_runtime_app.py tests/test_nex_cx_processing.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
