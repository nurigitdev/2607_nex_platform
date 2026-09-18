# Slice 0821: AG acknowledgement expiry automation boundary audit

## Objective

Start S83 by fixing the runtime boundary for automatically invoking the S82
acknowledgement expiry reconciliation worker.

## Decisions

- Reuse `run_operator_review_liveness_ack_expiry_reconciliation` and its
  compare-and-set persistence adapter.
- Use an externally scheduled, bounded run-once command instead of creating a
  continuous in-process loop or supervised subprocess in S83.
- Keep automation disabled by default and require explicit enablement.
- Reuse `ag_op_review_ack_state` and `service_operational_events`; no new table
  or protected route is introduced by this boundary slice.
- Keep retention and physical deletion outside S83.

## Planned Slices

- Slice 0822: automation policy contract.
- Slice 0823: read-only tick plan.
- Slice 0824: bounded tick execution.
- Slice 0825: executable CLI facade.
- Slice 0826: lifecycle audit events.
- Slice 0827: operations projection.
- Slice 0828: real `nex_ag_test` PostgreSQL smoke.
- Slice 0829: privacy and runbook evidence.
- Slice 0830: S83 closure.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_ag_ack_expiry_automation_boundary_audit.py --summary
./.venv/bin/pytest tests/test_ag_ack_expiry_automation_boundary_audit.py -q --tb=short
```

Boundary result:
`ag_ack_expiry_automation_boundary=pass mode=externally_scheduled_bounded_run_once new_table=False continuous_loop=False next=Slice_0822_automation_policy`.

Focused regression result: `7 passed`.

Full regression result: `5418 passed, 1 warning`.

- Statement coverage: `69339 / 70222 = 98.742559311897%`.
- Branch coverage: `16407 / 17058 = 96.183608863876%`.
- Boundary runner statement coverage: `100%`.
