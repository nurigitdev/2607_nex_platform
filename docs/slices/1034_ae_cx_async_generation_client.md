# Slice 1034: AE CX Asynchronous Generation Client

## Goal

Provide one AE transport adapter for the complete owner-scoped CX asynchronous
generation lifecycle.

## Implementation

- Added typed admission, job polling, handoff polling, and cancellation methods.
- Every request carries AE service authority, request/trace lineage, and
  canonical tenant/subject owner headers.
- Admission requires an idempotency key; job identifiers are URL-escaped.
- Timeouts, connection failures, CX problem responses, invalid JSON, and
  non-object success bodies normalize to stable AE client errors.
- The adapter defaults to a 10-second control-plane timeout and does not wait
  for provider generation.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_cx_async_generation_client.py \
  --coverage-target services/nex-ae-api/nex_ae_api/cx_async_generation_client.py
```

Tests use an in-process mocked HTTP transport. No database or provider call is
required.

## Observed Evidence

- Focused transport tests: `15 passed`.
- Slice Gate: `2154 passed` with one known warning.
- Repository statement coverage: `97.90%`.
- Repository branch coverage: `95.72%`.
- New client statement/branch coverage: `100%`/`100%`.
- Contract validation: 96 schemas, 150 positive examples, 113 negative
  examples, and 7 OpenAPI documents.
