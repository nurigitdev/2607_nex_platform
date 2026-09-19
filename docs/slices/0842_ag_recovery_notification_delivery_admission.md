# Slice 0842: AG recovery notification delivery admission contract

## Objective

Apply the Slice 0841 option A decision as a deterministic, side-effect-free
admission contract before any recovery notification dispatch is persisted.

## Contract

`build_recovery_notification_delivery_admission` requires:

- an S84 notification plan in `READY` state with policy delivery authorized;
- no prior delivery or provider invocation reported by the plan;
- an explicit existing operator-review `case_id`;
- an explicit existing escalation whose `case_id` matches the case;
- matching `target_service`, `target_kind`, and `target_id` on both records;
- an allowed dispatch channel and bounded provider profile.

The result contains only verified IDs, target references, delivery selection,
safe notification classification, reason codes, and guardrail evidence. It does
not copy the complete notification payload.

## Guardrails

- No case or escalation is auto-created.
- No dispatch is persisted and no provider is invoked.
- No table, migration, route, or operational event is added.
- The default channel/profile remain `MOCK` / `mock-default` for bounded tests.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_delivery_admission.py \
  -q --tb=short \
  --cov=nex_ag.recovery_notification_delivery \
  --cov-branch --cov-report=term-missing
```

- Focused regression: `23 passed`.
- Delivery admission module statement/branch coverage: `100% / 100%`.
- Full regression: `5608 passed, 1 warning`.
- Statement coverage: `70633 / 71516` (`98.765311259019%`).
- Branch coverage: `16611 / 17262` (`96.228710462287%`).

The warning is the existing Starlette `TestClient` deprecation warning.
