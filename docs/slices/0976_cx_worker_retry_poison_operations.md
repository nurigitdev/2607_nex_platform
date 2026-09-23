# Slice 0976: CX Worker Retry and Poison Operations

## Goal

Make worker failure settlement deterministic: transient failures use bounded
backoff, while permanent and poison failures are dead-lettered immediately.

## Implementation

- Added explicit `TRANSIENT`, `PERMANENT`, and `POISON` failure classes.
- Classified typed validation, authorization, contract, non-retryable, and
  selected 4xx failures as permanent.
- Added bounded exponential backoff through the shared `JobRetryPolicy`.
- Added a shared `dead_letter_job` operation so poison jobs persist a safe
  error code and dead-letter marker without consuming all remaining attempts.
- Wired the bounded CX runtime through the new failure settlement policy.
- Added a metadata-only dead-letter projection that excludes job payloads and
  exception details.
- Kept the original Full Gate available; this fifth Slice additionally runs
  the requirement-relative Checkpoint Gate.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_worker_resilience.py \
  tests/test_nex_cx_worker_runtime.py \
  tests/test_nex_runtime_jobs.py \
  --cov=nex_cx.worker_resilience --cov=nex_cx.worker_runtime \
  --cov=nex_runtime.jobs --cov-branch --cov-report=term-missing
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_worker_resilience.py \
  --test tests/test_nex_cx_worker_runtime.py \
  --test tests/test_nex_runtime_jobs.py \
  --test tests/test_cx_worker_operations_resilience_boundary_audit.py \
  --coverage-target services/nex-cx/nex_cx/worker_resilience.py \
  --smoke scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py
scripts/quality/run_checkpoint_gate.sh
```

Observed result:

- focused regression: `65 passed`
- Slice Gate: `2035 passed`
- Slice Gate statement coverage: `98.79%`
- Slice Gate branch coverage: `97.80%`
- `nex_cx.worker_resilience`: `100%` statement and branch coverage
- `nex_cx.worker_runtime`: `100%` statement and branch coverage
- `nex_runtime.jobs`: `96.15%` statement and `95.45%` branch coverage
- Checkpoint Gate: `7194 passed`
- Checkpoint statement coverage: `98.60%`
- Checkpoint branch coverage: `96.43%`
- contract validation: `90` schemas, `141` positive examples, `106`
  negative examples, and `7` OpenAPI documents

PostgreSQL and DGX are not required for this deterministic policy Slice.
