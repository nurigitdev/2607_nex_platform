# Slice 0856: AG recovery notification live contract hardening

## Objective

Freeze S86 live admission and safe execution diagnostics in JSON Schema,
OpenAPI, positive examples, and negative privacy examples.

## Implementation

- Added `confirm_live_delivery` to the delivery request contract.
- Added the non-invoking live admission summary to delivery mutation responses.
- Added nullable safe execution diagnostics to recovery delivery read-model
  items.
- Added positive live mutation and live execution projection fixtures.
- Added a negative provider-endpoint leak fixture.
- Kept endpoint values, authorization material, tokens, raw payloads, request
  signatures, and input payload hashes outside the external contract.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./.venv/bin/pytest -q --tb=short \
  tests/test_nex_ag_recovery_notification_contracts.py \
  tests/test_nex_ag_recovery_notification_live_delivery_api.py \
  tests/test_nex_ag_recovery_notification_live_execution.py
```
