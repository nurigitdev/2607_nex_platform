# Slice 0112: Worker Heartbeat Persistence Foundation

## Scope

Slice 0112 persists `worker_heartbeat.v1` through the same service-owned
database pattern used by common jobs and operational events.

## Runtime Store

The shared runtime now exposes:

- `WorkerHeartbeatStore`
- `InMemoryWorkerHeartbeatStore`
- `SqlAlchemyWorkerHeartbeatStore`
- `worker_heartbeat_store_from_app()`

`ServicePersistenceRuntime` now carries `worker_heartbeat_store` in both memory
and PostgreSQL modes. Memory mode remains the default for regression tests.
PostgreSQL mode uses the worker session factory because heartbeat writes are
owned by worker/job execution paths.

## Database Shape

Every service database adds:

```text
service_worker_heartbeats
```

The table uses `(service_id, worker_id)` as the primary key, stores JSONB
metadata, enforces `worker_heartbeat.v1`, preserves `BUSY` heartbeats with an
`active_job_id`, and indexes service/status, worker type/status, last seen, and
active job lookups.

## Regression Split

SQLite regression covers adapter behavior: upsert, update, filtering, summaries,
copy isolation, and unavailable-store errors. PostgreSQL DDL remains canonical
through service migrations and database foundation tests.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_database_schema_foundation.py tests/test_nex_runtime_persistence.py tests/test_nex_runtime_worker_heartbeats.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
