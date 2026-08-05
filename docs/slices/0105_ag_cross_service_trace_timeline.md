# Slice 0105: AG Cross-Service Trace Timeline

## Scope

Slice 0105 adds a trace-centered AG operations endpoint:

```text
GET /admin/v1/operations/traces/{trace_id}
```

The endpoint gives operators one read-only view that mixes jobs and operational
events associated with the same cross-service trace.

## Response Shape

The projection schema version is:

```text
ag_cross_service_trace_timeline_projection.v1
```

Each timeline item has a stable `timeline_item_type`, `item_id`, `service_id`,
`trace_id`, `operation_timestamp`, and either a redacted `event` object or a
service-scoped `job` object.

## Query Contract

The route reuses the Slice 0101 operations query fields:

- `service_id`
- `since`
- `until`
- `sort`
- `cursor`
- `limit`

Jobs use `updated_at` as the operation timestamp, falling back to `created_at`
through the shared operation timestamp helper. Events use `created_at`.

## Source Status

Job queues are scanned per selected service and report the same status family as
the job operations projection:

- `READY`
- `NOT_CONFIGURED`
- `UNAVAILABLE`

The event source reports `READY` or `UNAVAILABLE`. The overall projection is
`DEGRADED` when any selected job source is missing/unavailable or the event
source is unavailable.

## SQLite/PostgreSQL Strategy

The trace timeline stays above the SQL adapter layer for now. Regression tests
use in-memory sources, while PostgreSQL behavior is covered by the existing
operations source registry and guarded smoke packs. This avoids introducing
SQLite/PostgreSQL DDL or query dialect drift in Slice 0105.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_runtime_app.py
```

Observed result:

```text
91 passed
```
