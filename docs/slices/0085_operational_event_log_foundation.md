# Slice 0085: Operational event/log foundation

## Intent

Slice 0085 adds the first shared operational event/log foundation for service
monitoring and later AG log views. It is intentionally read-only and mock-first:
services can build and store safe events in memory, every service database has a
future write-through table, and AG can project filtered events.

## Runtime Behavior

`nex_runtime.operational_events` provides:

- `operational_event.v1` event construction
- severity validation for `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`
- recursive detail redaction for password, token, authorization, API key,
  secret, raw prompt, raw user message, and source text keys
- in-memory append/get/list/filter behavior
- limit clamping and summaries by severity and service

## AG Projection

AG now registers:

```text
GET /admin/v1/operations/events
```

The route requires a valid AG service claim and supports:

- `service_id`
- `severity`
- `event_type`
- `trace_id`
- `limit`

The response schema version is `ag_operational_event_projection.v1`.

## Database Shape

Every service gets `0085_service_operational_events_foundation.sql`, creating
`service_operational_events` with redaction-safe event metadata and indexes for
service, severity, trace, and event-type lookup.

## Deferred

Service write-through into `service_operational_events` is deferred until the
service repositories adopt the shared operational event store.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_operational_events.py tests/test_nex_ag_operations.py tests/test_database_schema_foundation.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
