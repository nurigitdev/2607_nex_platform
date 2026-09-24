# Slice 0989: CX Async Generation Contract, OpenAPI, and Observability

## Goal

Publish the owner-safe asynchronous generation job boundary and make admission
and cancellation visible without exposing private generation material.

## Implementation

- Added `cx_async_generation_job.v1` JSON Schema with valid and negative
  examples.
- Added owner-scoped admission, polling, and cancellation operations to the CX
  OpenAPI contract.
- Added deterministic metadata-only events for enqueue, join, replay, and
  cancellation transitions.
- Kept prompt text, request envelopes, tenant IDs, owner IDs, provider secrets,
  and provider response detail outside operational events.

Remote providers are intentionally not required by this Slice. Deterministic
mock execution remains the S99 test provider while connectivity is unavailable.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
./.venv/bin/pytest -q \
  tests/test_nex_cx_async_generation_observability.py \
  tests/test_nex_cx_async_generation_operations.py \
  tests/test_contract_validation.py \
  --cov=nex_cx.async_generation_observability \
  --cov=nex_cx.async_generation_operations \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_async_generation_recovery_boundary_audit.py --summary
```
