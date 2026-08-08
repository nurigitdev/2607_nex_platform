# Slice 0137: Service Log Persistence Foundation

## Scope

Slice 0137 persists the structured service log shape introduced in Slice 0136.
The foundation remains service-local: every service owns its own
`service_log_entries` table, and future AG log search should read those stores
without writing into service databases.

Implemented:

- `0137_service_log_entries_foundation.sql` for all five service databases
- `ServiceLogStore` protocol
- `InMemoryServiceLogStore`
- `SqlAlchemyServiceLogStore`
- `service_log_store_from_app()` fallback lookup
- `ServicePersistenceRuntime.service_log_store`

## Storage Shape

`service_log_entries` stores:

- `service_log_entry.v1` identity and severity
- logger/message with bounded text lengths
- trace/request/job/subject correlation fields
- redaction-safe `attributes` JSONB
- `redacted_attribute_keys` JSONB
- `observed_at`

Indexes cover service, severity, logger, trace, request, job, and subject
search paths.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_service_logs.py tests/test_nex_runtime_persistence.py tests/test_database_schema_foundation.py
```
