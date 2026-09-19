# Slice 0841: AG recovery notification delivery boundary audit

## Objective

Start S85 by deciding whether S84 recovery notification previews may cross
into persisted outbound delivery. This Slice audits the existing dispatch
foundation but does not persist or deliver a notification.

## Finding

The existing `ag_op_esc_dispatches` outbox, SQLAlchemy store, execution worker,
and provider adapters are reusable. However, every outbox row requires both an
existing `case_id` and an existing `escalation_id` through non-null foreign
keys. S84 recovery notification previews do not create either record.

This is an implementation boundary, not a minor detail. Automatically creating
operator-review cases or escalations would change their lifecycle semantics,
while a separate outbox would add another persistence and execution path.

## Decision Required

Recommended option:
`reuse_existing_dispatch_outbox_with_explicit_case_escalation_context`.

- Require callers to supply an existing `case_id` and `escalation_id`.
- Reuse `ag_op_esc_dispatches`, its SQLAlchemy store, worker, retry policy, and
  notification provider adapters.
- Do not auto-create a case or escalation from a liveness recovery preview.
- Add no new delivery table.

Alternatives:

- `create_dedicated_recovery_notification_outbox`: permit delivery without an
  operator-review case, but add a table and adapt/duplicate execution logic.
- `record_operational_event_without_delivery`: keep recovery notifications
  internal and leave external delivery outside S85.

Until one option is accepted, `safe_to_implement_next_slice` is `false`.

## Guardrails

- S84 remains preview-only: provider invocation and dispatch persistence stay
  forbidden.
- Slice 0841 adds no table, migration, route, runtime state mutation, or
  provider call.
- The existing table name `ag_op_esc_dispatches` is 20 characters and remains
  within the 30-character project guideline.

## Provisional Slices

- Slice 0842: delivery admission contract.
- Slice 0843: existing dispatch outbox handoff planner.
- Slice 0844: protected delivery request API.
- Slice 0845: delivery read model and operations projection.
- Slice 0846: contract and OpenAPI hardening.
- Slice 0847: bounded mock execution integration.
- Slice 0848: actual `nex_ag_test` PostgreSQL smoke.
- Slice 0849: privacy and operator runbook evidence.
- Slice 0850: S85 closure.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_delivery_boundary_audit.py \
  --summary
./.venv/bin/pytest \
  tests/test_ag_recovery_notification_delivery_boundary_audit.py \
  -q --tb=short \
  --cov=run_ag_recovery_notification_delivery_boundary_audit \
  --cov-branch --cov-report=term-missing
```

Boundary result:
`ag_recovery_notification_delivery_boundary=pass decision=REQUIRED_BEFORE_IMPLEMENTATION recommended=reuse_existing_dispatch_outbox_with_explicit_case_escalation_context safe_next=False`.

- Focused regression: `6 passed`; audit runner statement coverage `100%`.
- Full regression: `5585 passed, 1 warning`.
- Statement coverage: `70550 / 71433` (`98.763876639648%`).
- Branch coverage: `16581 / 17232` (`96.222144846797%`).

The warning is the existing Starlette `TestClient` deprecation warning.
