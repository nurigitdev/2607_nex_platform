# Slice 0681: AG operator review case SLA/escalation boundary audit

## Intent

Start S69 by freezing the AG-owned operator review case SLA/escalation boundary
after S68 decision lifecycle closure.

## Scope

- Add
  `scripts/smoke/run_ag_operator_review_case_sla_escalation_boundary_audit.py`.
- Confirm S69 starts after the closed S68 decision lifecycle loop.
- Confirm Slice 0681 adds no database table.
- Confirm SLA/escalation projections reuse existing AG-owned sources:
  - `ag_op_cases`
  - `service_operational_events`
- Confirm outbound notification delivery and external incident-system sync stay
  deferred for S69.
- Confirm escalation starts as read-model payloads over case attention,
  assignment, priority, age, and lifecycle references.

## Decision

- `nex-ag` owns the SLA/escalation projection.
- The first implementation step after this audit is a case SLA policy/read-model
  foundation.
- SLA/escalation should derive from existing case rows, attention reason codes,
  priority, assignment refs, timestamps, latest action metadata, and safe
  operational-event context.
- Escalation candidates should link to existing case queue, detail, timeline,
  closure packet, and operations issue-candidate surfaces.
- A dedicated escalation/acknowledgement table is deferred until acknowledgement
  history, notification delivery, or retention requirements prove it is
  necessary. `ag_op_escalations` is reserved as a short future candidate name.
- Notification delivery and external incident-system sync remain deferred.
- PostgreSQL smoke evidence for the SLA/escalation path must use the real
  `nex_ag_test` database before S69 closure.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_case_sla_escalation_boundary_audit.py tests/test_ag_operator_review_case_sla_escalation_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_case_sla_escalation_boundary_audit.py -q --cov=run_ag_operator_review_case_sla_escalation_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_case_sla_escalation_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
ag_operator_review_case_sla_escalation_boundary_audit=pass paths=22/22 tokens=29/29 token_groups=7/7 tables=3/3 boundary=ag_owned_operator_review_case_sla_escalation escalation=read_model_first notification=deferred next=Slice_0682
```
