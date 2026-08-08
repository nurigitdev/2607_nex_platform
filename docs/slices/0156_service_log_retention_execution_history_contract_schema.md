# Slice 0156: Service Log Retention Execution History Contract Schema

## Scope

Slice 0156 introduces the contract and runtime validation foundation for
service log retention execution history.

Implemented:

- `service_log_retention_history_entry.v1` JSON Schema
- positive and negative contract fixtures
- `SERVICE_LOG_RETENTION_HISTORY_ENTRY_SCHEMA_VERSION`
- `build_service_log_retention_history_entry(...)`
- `validate_service_log_retention_history_entry(...)`
- retention history query limit normalization constants

## Shape

The history entry preserves the full `service_log_retention_execution.v1`
payload under `execution` and duplicates the fields operators need for
filtering, sorting, and rollups:

- service id
- mode and execution status
- retention cutoff, checked time, and recorded time
- candidate and deleted counts
- request, trace, idempotency, blocked, and error fields

Runtime validation checks that duplicated summary fields match the embedded
execution payload. This keeps history records compact to query while preserving
the original execution evidence.

## Boundaries

This Slice does not yet add persistence tables, service-local history query
routes, AG history projection, issue rules, or OpenAPI surfaces. Those are
reserved for Slices 0157-0160.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_service_logs.py tests/test_contract_validation.py
```

