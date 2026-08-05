# Slice 0097: AG unified operations projection

## Intent

Slice 0097 adds one AG endpoint for reading job and operational event state
together. This lets operators inspect request/job/event correlation without
making separate calls while preserving the older focused endpoints.

## Runtime Behavior

AG now registers:

```text
GET /admin/v1/operations
```

The route requires a valid AG service claim and supports:

- `service_id`
- `job_status`
- `job_type`
- `event_severity`
- `event_type`
- `trace_id`
- `limit`

The response schema version is `ag_unified_operations_projection.v1`. It embeds
the existing `ag_job_operations_projection.v1` and
`ag_operational_event_projection.v1` payloads, plus a combined summary and the
source registry summary when a registry is injected.

## Compatibility

`GET /admin/v1/operations/jobs` and `GET /admin/v1/operations/events` remain
unchanged. The unified route reuses the same builders and filter validation
rules instead of creating a second operations model.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_runtime_app.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
