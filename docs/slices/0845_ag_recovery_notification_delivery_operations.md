# Slice 0845: AG recovery notification delivery operations projection

## Objective

Expose persisted S85 delivery requests as a safe read model for operators and
integrate it into the existing NeX-AG operations dashboard.

## Read Model

The projection selects only existing escalation dispatch rows whose metadata
contains the S85 `recovery_notification_delivery` marker. It reports:

- total and status counts;
- whether execution attempts have occurred;
- recent dispatch IDs, case/escalation references, safe previews, state, and
  timestamps;
- the existing `ag_op_esc_dispatches` table as its source.

`GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-notification-deliveries`
returns the protected read model. The same projection is nested under the
dashboard recovery-notification section.

## Guardrails

- Request signatures, hashes, idempotency keys, endpoints, tokens, database
  URLs, and raw payloads are excluded.
- Unrelated escalation dispatches are excluded.
- A source failure produces a redacted `DEGRADED` projection.
- The dashboard schema accepts the nested delivery projection; strict field
  freezing remains Slice 0846 scope.
- No table, migration, mutation, or provider call is added.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_operations.py \
  tests/test_nex_ag_recovery_notification_delivery_api.py \
  -q --tb=short \
  --cov=nex_ag.recovery_notification_operations \
  --cov-branch --cov-report=term-missing
```

- Related operations/API regression: `239 passed, 1 warning`.
- Recovery notification operations module statement/branch coverage:
  `100% / 100%`.
- Full regression: `5644 passed, 1 warning`.
- Statement coverage: `70792 / 71675` (`98.768050226718%`).
- Branch coverage: `16663 / 17314` (`96.240036964306%`).

The warning is the existing Starlette `TestClient` deprecation warning.
