# Slice 0985: CX Async Generation Idempotent Queue Admission

## Goal

Join durable generation admission, private request persistence, and
`service_jobs` enqueue without losing retry safety across partial failures.

## Result

- Existing synchronous admission behavior remains unchanged.
- Async admission may join an identical in-progress reservation.
- Generation and job identities are deterministic for each owner/idempotency
  key.
- Immutable request persistence occurs before enqueue; an enqueue failure can
  be retried by joining the reservation and safely enqueueing the same job.
- Existing jobs must match the private envelope hash, size, admission, tenant,
  and owner or fail with an idempotency conflict.
- Terminal generation replay returns the durable generation and any associated
  job without another provider call.

No new table and no remote provider are required.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_async_generation.py \
  tests/test_nex_cx_generation_runtime.py \
  --cov=nex_cx.async_generation --cov=nex_cx.generation_runtime \
  --cov-branch --cov-report=term-missing
```
