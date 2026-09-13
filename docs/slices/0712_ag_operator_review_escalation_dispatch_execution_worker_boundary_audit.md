# Slice 0712: AG escalation dispatch execution worker boundary audit

## Intent

Start S72 by freezing the AG-owned execution-worker boundary for persisted S71
escalation dispatch outbox rows.

## Scope

- Add
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py`.
- Confirm Slice 0712 adds no database table.
- Confirm the execution worker reads the existing `ag_op_esc_dispatches` outbox
  and records safe attempt history through `service_operational_events`.
- Confirm S72 starts with bounded run-once, mock-first worker behavior before any
  daemon loop or live outbound provider delivery.
- Confirm live notification delivery and live external incident sync stay
  deferred at the S72 boundary.
- Confirm raw provider payloads, raw notification payloads, raw external incident
  payloads, provider secrets, database URLs, service tokens, raw comments, raw
  source text, and raw idempotency keys remain out of database/evidence surfaces.

## Decision

`nex-ag` owns the dispatch execution worker boundary. S72 should first execute
bounded, explicitly opted-in mock worker batches over eligible
`ag_op_esc_dispatches` rows and reuse the existing dispatch state machine for
`START`, `SUCCEED`, `FAIL`, `RETRY`, and `CANCEL` transitions. The first worker
implementation should persist only safe result hashes, statuses, counters,
previews, and operational events. Continuous daemon execution and live
notification/external-incident delivery remain deferred until later protected
live slices.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py tests/test_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py -q --cov=run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
ag_operator_review_escalation_dispatch_execution_worker_boundary_audit=pass paths=19/19 tokens=27/27 token_groups=8/8 tables=4/4 boundary=ag_owned_operator_review_escalation_dispatch_execution_worker dispatch_table=ag_op_esc_dispatches worker=bounded_mock_first_only provider=mock_first_only live_delivery=deferred next=Slice_0713
```
