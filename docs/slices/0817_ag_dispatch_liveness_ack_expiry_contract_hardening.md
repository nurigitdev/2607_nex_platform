# Slice 0817: AG dispatch liveness acknowledgement expiry contract hardening

## Objective

Freeze the S82 expiry reconciliation runtime shape in checked-in OpenAPI and
operations JSON Schema contracts.

## Changes

- Added the protected bounded reconciliation POST path to the static AG OpenAPI.
- Added request, result, outcome, route, and dashboard expiry-overlay schemas.
- Required the expiry reconciliation overlay in the AG operations projection.
- Corrected stale recovery-policy metadata to identify the active
  `ag_op_review_ack_state` persistence table.
- Added runtime/static route drift and contract invariant regression tests.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./.venv/bin/pytest tests/test_nex_ag_liveness_ack_expiry_contracts.py tests/test_contract_validation.py tests/test_nex_ag_operations.py -q --tb=short
```

Contract validation result:
`contract_validation=pass schemas=77 examples=123 negative_examples=87 openapi=7`.

Focused regression result: `240 passed, 1 warning`.

Full regression result: `5389 passed, 1 warning`.

- Statement coverage: `68937 / 69820 = 98.735319392724%`.
- Branch coverage: `16373 / 17024 = 96.175986842105%`.
