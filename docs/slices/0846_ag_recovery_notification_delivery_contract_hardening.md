# Slice 0846: AG recovery notification delivery contract hardening

## Objective

Freeze the S85 protected delivery request and read-model surfaces in JSON
Schema and OpenAPI without changing their runtime behavior.

## Contract

The delivery contract now covers:

- explicit existing `case_id` and `escalation_id` request context;
- supported escalation dispatch channels and bounded provider profile names;
- idempotent `NEW` and `REPLAYED` persistence responses;
- the redacted delivery operations projection and recent safe dispatch items;
- the existing `ag_op_esc_dispatches` outbox as the source of truth;
- protected GET and POST route metadata and response status families.

The operations dashboard schema requires the nested delivery projection and
validates its counters, safe item fields, source status, and redaction flags.

## Guardrails

- The request schema rejects undeclared raw notification payloads.
- Read models reject request signatures, payload hashes, provider endpoints,
  tokens, database URLs, and idempotency keys.
- The POST contract does not auto-create an operator review case or escalation.
- Provider invocation remains outside this Slice; the mutation contract fixes
  `provider_invocation_performed` to `false`.
- No table or migration is added.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./.venv/bin/pytest -q \
  tests/test_nex_ag_recovery_notification_contracts.py \
  tests/test_nex_ag_recovery_notification_delivery_api.py \
  tests/test_nex_ag_recovery_notification_operations.py
```

- Contract validation: `78` schemas, `124` positive examples, `88` negative
  examples, and `7` OpenAPI documents passed.
- Focused contract/API/operations regression: `33 passed, 1 warning`.
- Full regression: `5646 passed, 1 warning`.
- Statement coverage: `70792 / 71675` (`98.768050226718%`).
- Branch coverage: `16663 / 17314` (`96.240036964306%`).

The warning is the existing Starlette `TestClient` deprecation warning.
