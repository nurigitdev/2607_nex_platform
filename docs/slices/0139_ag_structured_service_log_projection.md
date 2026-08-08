# Slice 0139: AG Structured Service Log Projection

## Scope

Slice 0139 exposes service-local structured logs through the AG operations
surface without giving AG write access to service databases.

Implemented:

- `ReadOnlyServiceLogStore`
- `RegistryServiceLogStore`
- `OperationsSource.service_log_store`
- `OperationsSourceRegistry.service_log_stores()`
- PostgreSQL read-only service log source wiring
- `GET /admin/v1/operations/logs`
- `GET /admin/v1/operations/logs/{log_id}`
- AG operations projection schema support for `ag_service_log_projection.v1`
  and `ag_service_log_detail_projection.v1`

## Query Shape

The log list endpoint supports service, severity, logger, trace, request, job,
subject, free-text query, time window, sort, cursor, and limit filters. The
projection returns source status per service so operators can distinguish empty
results from missing or unavailable service log stores.

AG only reads the service-local `service_log_entries` stores. Writes remain
service-owned and flow through each service's `ServiceLogEmitter`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py
./.venv/bin/python scripts/quality/validate_contracts.py contracts
```
