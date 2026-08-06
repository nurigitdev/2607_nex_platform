# Slice 0115: Worker Heartbeat Emitter Runtime Helper

## Scope

Slice 0115 adds a shared `WorkerHeartbeatEmitter` to `nex_runtime`.

The emitter wraps `worker_heartbeat.v1` construction and store writes so service
workers can report lifecycle state without duplicating payload shape,
`started_at` handling, metadata merging, or app persistence lookup behavior.

## Runtime Helper

The helper supports direct emission for strict worker flows and `safe_emit()`
for observability writes that must not fail the primary job path.

Convenience methods cover common worker lifecycle states:

- `starting()`
- `idle()`
- `busy(active_job_id=...)`
- `stopping()`
- `stopped()`
- `error()`

`worker_heartbeat_emitter_from_app()` resolves the configured service
`WorkerHeartbeatStore` from `app.state.nex_persistence` and keeps the existing
in-memory fallback for local regression.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_worker_heartbeats.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
