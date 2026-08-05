# Slice 0098: Service operational event taxonomy registry

## Intent

Slice 0098 makes operational event type metadata explicit. The first registry
scope is CX document processing, because those events are now written through
memory and PostgreSQL paths and are visible in AG projections.

## Runtime Behavior

`nex_runtime.operational_events` now provides:

- `OperationalEventTypeSpec`
- `DEFAULT_OPERATIONAL_EVENT_TAXONOMY`
- `list_operational_event_taxonomy`
- `operational_event_taxonomy_by_type`
- `summarize_operational_event_taxonomy`
- shared CX processing event constants

Registered CX processing event types:

- `cx.processing.started`: `INFO`, subject `cx.document`
- `cx.processing.succeeded`: `INFO`, subject `cx.document`
- `cx.processing.failed`: `ERROR`, subject `cx.document`

Each taxonomy record lists the redaction-safe detail keys allowed for the event
type. Sensitive detail keys such as API keys, tokens, passwords, raw prompts,
or source text are rejected during taxonomy construction.

## AG Projection

AG now registers:

```text
GET /admin/v1/operations/event-taxonomy
```

The route requires a valid AG service claim and supports `service_id` and
`event_type` filters. The response schema version is
`ag_operational_event_taxonomy_projection.v1`.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_operational_events.py tests/test_nex_ag_operations.py tests/test_nex_cx_processing.py tests/test_nex_runtime_app.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
