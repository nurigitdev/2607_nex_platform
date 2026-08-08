# Slice 0138: Service Log Emitter Runtime Integration

## Scope

Slice 0138 turns the structured service log contract and persistence adapter
into a runtime write path.

Implemented:

- `ServiceLogEmitResult`
- `ServiceLogEmitter`
- `service_log_emitter_from_app()`
- optional `ServiceLogEmitter` integration in `run_worker_once()`
- optional `ServiceLogEmitter` propagation through `run_worker_batch()`

The worker runner remains service-neutral. Services still own their job
handlers, stores, and logger naming, while `_shared` emits only bounded,
redaction-safe worker lifecycle diagnostics when an emitter is explicitly
provided.

## Worker Runtime Logs

The shared worker runner may emit:

- `Worker polling started.`
- `Worker did not claim a job.`
- `Worker job claim failed.`
- `Worker claimed a job.`
- `Worker handler failed.`
- `Worker completed a job.`

Each log carries safe worker/job correlation attributes such as `worker_id`,
`worker_type`, `job_type`, `job_status`, and `attempt_count`. Exception details
are intentionally not copied into structured log attributes.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_service_logs.py tests/test_nex_runtime_worker_runner.py
```
