# Slice 0850: S85 AG recovery notification delivery closure

## Purpose

Close S85 by proving that an S84 recovery notification authorized for delivery
can enter the existing AG escalation dispatch outbox and complete a bounded
MOCK execution without weakening ownership, idempotency, or privacy boundaries.

## Closure

- Confirms option A: callers must supply an existing matching `case_id` and
  `escalation_id`; neither record is auto-created.
- Reuses `ag_op_esc_dispatches`, its SQLAlchemy store, transition planner,
  execution worker, retry semantics, and operations projection.
- Provides protected idempotent POST and redacted GET delivery routes.
- Freezes OpenAPI, JSON Schema, positive examples, and negative raw-payload
  examples.
- Executes only an explicitly selected dispatch in bounded `mock_first_only`
  mode and treats a completed repeat as `NOOP`.
- Preserves the internal request signature for conflict detection while
  removing it from mutation responses and read models.
- Records actual `nex_ag_test` migration, persistence, execution, direct SELECT,
  and cleanup evidence.
- Adds no table or index.

## Operational Boundary

S85 implements persisted MOCK delivery only. Live notification, email, webhook,
and incident channels remain blocked by the existing planner and require a
separate approved live-provider boundary. External network access is not part
of this closure.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_s85_ag_recovery_notification_delivery_closure.py \
  --summary
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./.venv/bin/pytest -q \
  tests/test_s85_ag_recovery_notification_delivery_closure.py \
  --cov=run_s85_ag_recovery_notification_delivery_closure \
  --cov-branch --cov-report=term-missing
```

Closure result:

```text
s85_ag_recovery_notification_delivery_closure=pass slice_range=0841-0850 postgres=True privacy=True mock_delivery=COMPLETED
```

Contract validation result:
`contract_validation=pass schemas=78 examples=124 negative_examples=88 openapi=7`.

- Closure runner: `7 passed`; statement/branch coverage `100% / 100%`.
- S85 focused regression: `116 passed, 1 warning`.
- Full regression: `5681 passed, 1 warning`.
- Statement coverage: `71165 / 72048` (`98.774428159005%`).
- Branch coverage: `16711 / 17362` (`96.250431977883%`).

The warning is the existing Starlette `TestClient` deprecation warning.
