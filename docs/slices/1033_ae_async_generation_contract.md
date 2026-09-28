# Slice 1033: AE Asynchronous Generation Contract

## Goal

Introduce a strict, privacy-safe AE contract for selecting asynchronous
generation and persisting the CX durable-job projection.

## Implementation

- Added `resolve_execution_strategy` with backward-compatible `SYNCHRONOUS`
  default and explicit `ASYNCHRONOUS` selection.
- Added `ae_async_generation.v1`, which stores only allowlisted CX job IDs,
  lifecycle status, attempts, safe links, retry flags, and error codes.
- Mapped `QUEUED`, `RUNNING`, and `SUCCEEDED` CX jobs to AE `PENDING` until a
  handoff is fetched. `FAILED` and `CANCELLED` map to AE `BLOCKED`.
- Rejected admissions without a durable job and projections containing content,
  external links, raw error details, inconsistent states, or invalid attempts.
- Kept generated content and private request data outside the AE projection.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_generation.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_generation.py
```

No database or provider call is required for this contract Slice.

## Observed Evidence

- Focused contract tests: `46 passed`.
- Slice Gate: `2139 passed` with one known warning.
- Repository statement coverage: `97.89%`.
- Repository branch coverage: `95.72%`.
- New contract statement/branch coverage: `100%`/`100%`.
- Contract validation: 96 schemas, 150 positive examples, 113 negative
  examples, and 7 OpenAPI documents.
