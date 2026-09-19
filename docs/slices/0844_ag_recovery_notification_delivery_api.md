# Slice 0844: AG recovery notification protected delivery API

## Objective

Expose the option A flow as a protected, idempotent POST operation that reuses
the existing escalation dispatch outbox.

## Route

`POST /admin/v1/operator-review/dispatch-daemon/liveness/recovery-notification-deliveries`

The request requires `case_id`, `escalation_id`, and `Idempotency-Key`.
`channel_type` and `provider_profile` are optional and default to the bounded
mock selection.

The server rebuilds the current recovery notification plan; clients cannot
submit or replace the notification plan. It then loads the existing case and
escalation, verifies their relationship, builds the existing dispatch record,
and persists it through the injected dispatch store.

## Idempotency

- The first accepted request returns `201` and `NEW`.
- An identical replay returns `200` and `REPLAYED`.
- Reusing the key with a different plan or provider selection returns `409`.

## Guardrails

- Delivery policy must explicitly authorize delivery.
- Only an existing case and its matching escalation are accepted.
- Live channels remain blocked by the existing dispatch planner.
- Persistence does not invoke a provider.
- No new table or migration is added.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_delivery_api.py \
  tests/test_nex_ag_recovery_notification_dispatch_handoff.py \
  tests/test_nex_ag_recovery_notification_delivery_admission.py \
  -q --tb=short \
  --cov=nex_ag.recovery_notification_delivery \
  --cov=nex_ag.operations \
  --cov-branch --cov-report=term-missing
```

- Focused regression: `54 passed, 1 warning`.
- Delivery module statement/branch coverage: `100% / 100%`.
- Full regression: `5639 passed, 1 warning`.
- Statement coverage: `70746 / 71629` (`98.767259071047%`).
- Branch coverage: `16653 / 17304` (`96.237864077670%`).

The warning is the existing Starlette `TestClient` deprecation warning.
