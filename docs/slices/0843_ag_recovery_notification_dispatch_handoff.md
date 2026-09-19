# Slice 0843: AG recovery notification dispatch handoff planner

## Objective

Convert an admitted recovery notification into the existing operator-review
escalation dispatch plan without persisting the resulting outbox record.

## Behavior

- Revalidates that the S84 plan remains delivery-ready.
- Rejects drift between notification plan, admission, and escalation context.
- Maps only the redacted title and summary into `safe_subject` and `safe_body`.
- Reuses `build_operator_review_escalation_dispatch_plan` and its deterministic
  dispatch record/idempotency behavior.
- Marks a mock handoff `READY_TO_PERSIST` while leaving persistence to Slice
  0844.
- Preserves the existing `live_channel_deferred` block for non-mock channels.

## Guardrails

- No new table, migration, route, persistence operation, or provider call.
- Raw recovery plans and provider secrets are not copied into the dispatch.
- No case or escalation is auto-created.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_dispatch_handoff.py \
  tests/test_nex_ag_recovery_notification_delivery_admission.py \
  -q --tb=short \
  --cov=nex_ag.recovery_notification_delivery \
  --cov-branch --cov-report=term-missing
```

- Focused regression: `41 passed`.
- Delivery handoff module statement/branch coverage: `100% / 100%`.
- Full regression: `5626 passed, 1 warning`.
- Statement coverage: `70668 / 71551` (`98.765915221311%`).
- Branch coverage: `16625 / 17276` (`96.231766612642%`).

The warning is the existing Starlette `TestClient` deprecation warning.
