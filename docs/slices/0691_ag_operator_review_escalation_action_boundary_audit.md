# Slice 0691: AG operator review escalation action boundary audit

## Intent

Start S70 by freezing the AG-owned operator review escalation action boundary
after S69 SLA/escalation closure.

## Scope

- Add
  `scripts/smoke/run_ag_operator_review_escalation_action_boundary_audit.py`.
- Confirm S70 starts after the closed S69 SLA/escalation read-model loop.
- Confirm Slice 0691 adds no database table.
- Reserve the short AG-owned table name `ag_op_escalations` for the next
  persistence slice.
- Confirm escalation action state will persist only acknowledgement, snooze,
  dismissal, reopen, and safe operator action metadata.
- Confirm raw comments, raw prompts, raw source text, raw notification payloads,
  raw external incident payloads, secrets, and raw idempotency keys remain out
  of response/evidence surfaces.
- Confirm outbound notification delivery and external incident-system sync stay
  deferred for S70.

## Decision

- `nex-ag` owns the escalation action loop.
- S70 overlays operator acknowledgement/action state on top of the S69
  `ag_operator_review_case_escalations.v1` projection.
- The existing `ag_op_cases` table remains the case state source of record.
- `service_operational_events` remains the safe action-history and timeline
  source.
- `ag_op_escalations` is the planned short table name for persisted
  acknowledgement, snooze, and escalation-resolution state, starting in
  Slice 0692.
- Escalation actions should reuse the existing case action state machine when
  an action changes case status or assignment.
- Notification delivery and external incident sync remain deferred. S70 is an
  AG-internal operator action loop, not an outbound integration slice.
- PostgreSQL smoke evidence for the escalation action loop must use the real
  `nex_ag_test` database before S70 closure.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_escalation_action_boundary_audit.py tests/test_ag_operator_review_escalation_action_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_action_boundary_audit.py -q --cov=run_ag_operator_review_escalation_action_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_action_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
ag_operator_review_escalation_action_boundary_audit=pass paths=18/18 tokens=21/21 token_groups=7/7 tables=3/3 boundary=ag_owned_operator_review_escalation_action_loop persistence=planned_ag_owned_ack_state notification=deferred next=Slice_0692
```
