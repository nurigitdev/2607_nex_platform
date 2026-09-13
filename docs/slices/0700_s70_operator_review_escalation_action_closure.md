# Slice 0700: S70 operator review escalation action closure

## Intent

Close S70 by verifying the AG-owned persisted escalation action loop has its
runtime, contract, privacy, PostgreSQL smoke, documentation, and quality-gate
evidence in place.

## Scope

- Add `run_s70_operator_review_escalation_action_closure.py`.
- Confirm S70 covers Slice 0691 through Slice 0699.
- Confirm `ag_op_escalations` is the persisted escalation action-state table.
- Confirm `service_operational_events` remains the safe action-history source.
- Confirm notification delivery and external incident-system sync remain
  deferred.
- Confirm privacy regression and protected PostgreSQL smoke runners are wired
  into the default quality gate.

## Decision

S70 closes as an AG-internal operator escalation action loop. The loop persists
safe acknowledgement, snooze, dismiss, resolve, and reopen state in
`ag_op_escalations`; keeps case state anchored to `ag_op_cases`; records action
history through `service_operational_events`; and exposes safe list/detail/action
surfaces through the AG protected API, dashboard, issue-candidate projection,
contracts, and OpenAPI.

## Verification

```bash
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_s70_operator_review_escalation_action_closure.py -q --cov=run_s70_operator_review_escalation_action_closure --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_s70_operator_review_escalation_action_closure.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
s70_operator_review_escalation_action_closure=pass slice_range=0691-0700 required_files=32 boundary=ag_owned_operator_review_escalation_action_loop table=ag_op_escalations action_history=service_operational_events_first smoke=test_db_protected privacy=route_surface_regression
```
