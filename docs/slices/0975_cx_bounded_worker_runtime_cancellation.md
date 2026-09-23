# Slice 0975: CX Bounded Worker Runtime and Cancellation

## Goal

Provide a finite CX worker runner that cannot claim work indefinitely and lets
long-running handlers observe cancellation at explicit safe checkpoints.

## Implementation

- Added both max-job and max-duration limits to every worker batch.
- Added a cancellation token that re-reads durable job status at handler safe
  checkpoints.
- Reused the existing `CANCELLED` job transition as the durable cancellation
  request. Running handlers stop cooperatively instead of being terminated in
  the middle of a persistence operation.
- Added deterministic outcomes for success, cancellation, retry scheduling,
  dead-letter, idle, duration bound, and job-count bound.
- Redacted handler exception details and retained only a safe error code plus a
  constant operational detail.
- Kept result projections metadata-only and excluded handler return payloads.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_worker_runtime.py \
  --cov=nex_cx.worker_runtime --cov-branch --cov-report=term-missing
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_worker_runtime.py \
  --test tests/test_cx_worker_operations_resilience_boundary_audit.py \
  --coverage-target services/nex-cx/nex_cx/worker_runtime.py \
  --smoke scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py
```

Observed result:

- focused regression: `17 passed`
- Slice Gate: `1984 passed`
- statement coverage: `98.91%`
- branch coverage: `97.89%`
- `nex_cx.worker_runtime`: `100%` statement and branch coverage
- contract validation: `90` schemas, `141` positive examples, `106`
  negative examples, and `7` OpenAPI documents

PostgreSQL and DGX are not required for this deterministic runtime Slice.
