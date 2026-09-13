# Slice 0701: AG escalation outbound dispatch boundary audit

## Intent

Start S71 by freezing the AG-owned outbound dispatch boundary for persisted
operator review escalations after S70 closure.

## Scope

- Add
  `scripts/smoke/run_ag_operator_review_escalation_outbound_dispatch_boundary_audit.py`.
- Confirm Slice 0701 adds no database table.
- Reserve the short AG-owned dispatch/outbox table name
  `ag_op_esc_dispatches` for Slice 0702.
- Confirm S71 uses S70 persisted escalation action state as dispatch input.
- Confirm live notification delivery and live external incident sync stay
  deferred in S71.
- Confirm S71 uses mock-first provider execution and protected PostgreSQL smoke
  evidence before closure.
- Confirm raw notification payloads, raw external incident payloads, provider
  secrets, database URLs, service tokens, raw comments, raw source text, and raw
  idempotency keys remain out of database/evidence surfaces.

## Decision

`nex-ag` owns the outbound dispatch/outbox boundary. S71 may create safe dispatch
intent and attempt state after Slice 0702, but it must not perform live outbound
network delivery. Dispatch rows should reference `ag_op_escalations`, keep
dispatch history correlated through `service_operational_events`, store only
safe hashes/previews/refs/status fields, and leave actual provider integration
for a later protected-live slice.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_escalation_outbound_dispatch_boundary_audit.py tests/test_ag_operator_review_escalation_outbound_dispatch_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_outbound_dispatch_boundary_audit.py -q --cov=run_ag_operator_review_escalation_outbound_dispatch_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_outbound_dispatch_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
ag_operator_review_escalation_outbound_dispatch_boundary_audit=pass paths=18/18 tokens=22/22 token_groups=7/7 tables=4/4 boundary=ag_owned_operator_review_escalation_outbound_dispatch dispatch_table=ag_op_esc_dispatches provider=mock_first_only live_delivery=deferred next=Slice_0702
```
