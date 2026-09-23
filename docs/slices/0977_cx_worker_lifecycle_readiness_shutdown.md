# Slice 0977: CX Worker Lifecycle, Readiness, and Shutdown

## Goal

Expose explicit worker process lifecycle and stop claiming new work during a
graceful shutdown while allowing the active handler to settle safely.

## Implementation

- Added `STARTING`, `IDLE`, `BUSY`, `STOPPING`, `STOPPED`, and `ERROR`
  lifecycle control over the existing durable heartbeat store.
- Added readiness projection with missing, stale, starting, busy, stopping,
  stopped, and error reasons.
- Added an in-process shutdown latch. Once requested, the worker cannot claim
  another job.
- Integrated lifecycle emission with the bounded runtime before claim, during
  active work, after settlement, on typed failure, and at final shutdown.
- Kept process supervision external; lifecycle does not enqueue daemon-control
  jobs.
- Kept heartbeat metadata limited to job IDs, trace IDs, reason codes, and safe
  error codes.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_worker_lifecycle.py \
  tests/test_nex_cx_worker_runtime.py \
  --cov=nex_cx.worker_lifecycle --cov=nex_cx.worker_runtime \
  --cov-branch --cov-report=term-missing
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_worker_lifecycle.py \
  --test tests/test_nex_cx_worker_runtime.py \
  --test tests/test_cx_worker_operations_resilience_boundary_audit.py \
  --coverage-target services/nex-cx/nex_cx/worker_lifecycle.py \
  --coverage-target services/nex-cx/nex_cx/worker_runtime.py \
  --smoke scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py
```

Observed result:

- focused regression: `24 passed`
- Slice Gate: `1999 passed`
- statement coverage: `98.92%`
- branch coverage: `97.92%`
- `nex_cx.worker_lifecycle`: `100%` statement and branch coverage
- `nex_cx.worker_runtime`: `100%` statement and branch coverage
- contract validation: `90` schemas, `141` positive examples, `106`
  negative examples, and `7` OpenAPI documents

PostgreSQL and DGX are not required for this deterministic lifecycle Slice.
