# Slice 0117: Worker Lifecycle Operational Events

## Scope

Slice 0117 adds operational events for CX processing worker lifecycle
transitions.

New event taxonomy entries:

- `cx.worker.lifecycle.busy`
- `cx.worker.lifecycle.idle`
- `cx.worker.lifecycle.error`

These events complement, but do not replace, the existing
`cx.processing.started`, `cx.processing.succeeded`, and `cx.processing.failed`
events.

## Event Details

Worker lifecycle events use `subject_ref={"type": "worker", "id":
"cx-processing-inline-worker"}` and include safe correlation details:

- `worker_id`
- `worker_type`
- `worker_status`
- `pipeline_run_id`
- `document_id`
- `job_id`
- `job_status`
- `heartbeat_emit_ok`
- `heartbeat_error_code` when heartbeat emission fails

`BUSY` and `ERROR` events also include `active_job_id`. Terminal events include
`step_summary` when available, and `ERROR` includes `failed_step`.

## Smoke Evidence

The CX processing PostgreSQL OperationalEvent smoke now validates the persisted
worker lifecycle events in addition to processing started/succeeded events.
The AG cross-service observability smoke also expects the worker busy/idle
events in its unified event projection.

Smoke cleanup removes the inline worker heartbeat row created during the smoke
run.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_operational_events.py tests/test_nex_cx_processing.py tests/test_smoke_helpers.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
