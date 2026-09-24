# Slice 0988: CX Async Generation Owner Operations API

## Goal

Expose owner-scoped asynchronous admission, polling, and cancellation without
changing the existing synchronous generation API.

## Result

- `POST /api/v1/generation-jobs` validates the same grounded-generation
  boundary and returns `202` for enqueue/join or `200` for terminal replay.
- `GET /api/v1/generation-jobs/{job_id}` returns the metadata-only projection.
- `POST /api/v1/generation-jobs/{job_id}/cancel` supports queued and running
  cooperative cancellation.
- Queued cancellation immediately closes the generation as FAILED; running
  cancellation closes at the next worker checkpoint.
- Cross-owner access is indistinguishable from a missing job.
- Production bootstrap registers the private request store and specialized
  expired-lease recovery handler only when durable runtime is available.

No remote provider is required.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_async_generation_operations.py \
  tests/test_nex_cx_async_generation_recovery.py \
  --cov=nex_cx.async_generation_operations \
  --cov=nex_cx.async_generation_recovery --cov-branch \
  --cov-report=term-missing
```
