# Slice 0122: Service Worker Runner Foundation

## Scope

Slice 0122 adds a shared bounded worker runner to `nex_runtime`.

Implemented:

- `services/_shared/nex_runtime/worker_runner.py`
- `WorkerRunnerConfig`
- `WorkerJobExecution`
- `WorkerBatchResult`
- `run_worker_once()`
- `run_worker_batch()`
- package exports from `nex_runtime`

The runner intentionally stays domain-neutral. It owns the common mechanics of
claiming service jobs, emitting worker heartbeats, calling an injected
service-owned handler, and completing or failing the job. Service-specific
operational events and job payload semantics remain outside `_shared`.

## Runtime Behavior

`run_worker_once()` performs one bounded unit of work:

1. emit `STARTING`
2. claim the next queued job for the configured `job_type`
3. emit `IDLE` if no job is available
4. emit `BUSY` when a job is claimed
5. call the injected handler with a job copy
6. complete the job and emit `IDLE` on success
7. fail the job and emit `ERROR` on handler failure

`run_worker_batch()` repeats the one-shot runner up to `max_jobs`, stopping on
idle by default and stopping on the first failure unless `stop_on_failure=False`
is selected.

## Safety Boundary

Heartbeat writes use `WorkerHeartbeatEmitter.safe_emit()` so observability
failures do not hide the primary job result. Handler exceptions are converted
into safe error metadata using `error_code`/`detail` when available, otherwise
the exception class name is used.

The runner does not define new service event taxonomy, does not inspect source
documents, and does not know CX/AE/MO/OA/AG domain payloads.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_worker_runner.py tests/test_nex_runtime_worker_heartbeats.py tests/test_nex_runtime_jobs.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
