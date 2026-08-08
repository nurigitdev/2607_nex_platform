# Slice 0143: Trace Timeline Service Log Correlation

## Scope

Slice 0143 extends the AG cross-service trace timeline so a single trace can
show correlated jobs, operational events, and structured service logs together.

Implemented:

- `service_log_stores` support in the unified operations trace endpoint
- `log` timeline items in `ag_cross_service_trace_timeline_projection.v1`
- `log_source_statuses` in trace timeline projections
- dashboard smoke coverage for job/event/log timeline correlation
- contract schema and example updates

## Behavior

`GET /admin/v1/operations/traces/{trace_id}` now reads configured service-local
structured log stores by `trace_id` and emits timeline items with:

- `timeline_item_type=log`
- `item_id=log:{service_id}:{log_id}`
- `operation_timestamp=observed_at`
- full redaction-safe `service_log_entry.v1` payload under `log`

Log source availability mirrors Slice 0142:

- `READY` log sources contribute log timeline items.
- `UNAVAILABLE` log sources degrade the projection.
- `NOT_CONFIGURED` log sources are reported but do not degrade the trace
  timeline while structured service log rollout is still incremental.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_smoke_helpers.py tests/test_contract_validation.py
```

Operations smoke:

```bash
./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
```

