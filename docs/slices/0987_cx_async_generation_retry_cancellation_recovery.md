# Slice 0987: CX Async Generation Retry, Cancellation, and Recovery

## Goal

Make asynchronous generation converge after transient failures, cancellation,
attempt exhaustion, or worker loss.

## Result

- Intermediate retryable failures keep generation admission active.
- Permanent failures and exhausted attempts persist a metadata-only FAILED
  generation before the job dead-letters.
- Cooperative cancellation persists the same terminal generation outcome.
- Expired leases requeue through the S98 retry policy or dead-letter and close
  the generation when attempts are exhausted.
- Async generation is a specialized reconciliation workload, preventing a
  generic recovery path from losing generation state.
- Persisted failure detail is normalized and never includes provider/private
  error text.

No remote provider is required.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_async_generation_recovery.py \
  tests/test_nex_cx_async_generation_worker.py \
  --cov=nex_cx.async_generation_recovery \
  --cov=nex_cx.async_generation_worker --cov-branch \
  --cov-report=term-missing
```
