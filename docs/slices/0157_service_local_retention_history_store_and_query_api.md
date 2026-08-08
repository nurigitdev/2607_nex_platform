# Slice 0157: Service-Local Retention History Store and Query API

## Scope

Slice 0157 makes service log retention executions durable and queryable inside
each service boundary.

Implemented:

- service-owned `service_log_retention_history` migration for all five services
- `ServiceLogStore` retention history port methods:
  - `record_retention_history(...)`
  - `get_retention_history(...)`
  - `list_retention_history(...)`
- InMemory and SQLAlchemy retention history implementations
- automatic history recording for dry-run, blocked execute, and successful
  execute retention purges
- service-local history APIs:
  - `GET /internal/v1/service-logs/retention/history`
  - `GET /internal/v1/service-logs/retention/history/{execution_id}`
- `service_log_retention_history_list.v1` runtime response shape

## Persistence Boundary

Retention history is service-owned. AG and other services must query it through
service-local APIs or read-only operations sources; they should not write into
another service's history table.

The purge endpoint remains backward compatible: it still returns the original
`service_log_retention_execution.v1` evidence while recording the corresponding
history entry as a side effect.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_service_logs.py tests/test_db_migration_runner.py
```

