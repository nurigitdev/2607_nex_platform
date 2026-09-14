# Slice 0756: AG escalation dispatch daemon API contract hardening

## Intent

Publish and harden the S76 dispatch daemon API contract so AG operators and
client adapters can rely on stable tick-plan and tick-once route shapes.

## Implementation

- Updated `contracts/openapi/nex-ag.openapi.yaml` with:
  - `GET /admin/v1/operator-review/dispatch-daemon/tick-plan`
  - `POST /admin/v1/operator-review/dispatch-daemon/tick-plan`
  - `POST /admin/v1/operator-review/dispatch-daemon/tick-once`
- Added OpenAPI components for dispatch daemon control request, provider mode,
  route metadata, tick-plan projection, and tick-once projection.
- Hardened the control request contract to reject raw fields such as
  `provider_payload`, `database_url`, and idempotency material at the contract
  boundary.
- Refreshed the operations dashboard example so contract validation remains
  green with the current dispatch execution summary schema.
- Added a contract regression assertion in `tests/test_contract_validation.py`.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py contracts
```

Result: `contract_validation=pass schemas=77 examples=123 negative_examples=87 openapi=7`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py -k 'dispatch_daemon_api_contract or validate_contract_tree_accepts_valid_contract_package' -q
```

Result: `2 passed`.
