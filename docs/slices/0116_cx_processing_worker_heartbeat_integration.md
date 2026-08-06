# Slice 0116: CX Processing Worker Heartbeat Integration

## Scope

Slice 0116 connects the shared worker heartbeat emitter to the CX document
processing pipeline.

The MVP pipeline is still executed inline by the processing route, but it now
reports a stable worker identity:

- `worker_id`: `cx-processing-inline-worker`
- `worker_type`: `cx.document_processing.worker`

## Heartbeat Behavior

The processing pipeline emits heartbeat state without making the primary
pipeline depend on the heartbeat store.

- `BUSY` when the processing job starts running.
- `IDLE` when the processing job succeeds.
- `ERROR` when the processing job fails.

Heartbeat metadata includes `document_id`, `pipeline_run_id`, `job_id`,
`job_status`, and final `step_summary` when available. Failure heartbeats also
include `failed_step`.

## Route Wiring

`register_processing_routes()` resolves the worker heartbeat store through
`app.state.nex_persistence` by default. Tests can also inject a
`WorkerHeartbeatEmitter` directly.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_processing.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
