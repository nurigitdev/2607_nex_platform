# Slice 0641: AG Operator Review Case/Action Boundary Audit

Slice 0641 starts S65 by freezing the AG-owned operator review case/action
boundary before adding case persistence, action routes, dashboard correlation,
contracts, and PostgreSQL smoke evidence.

## Scope

- Adds a smoke/audit checkpoint for the AG operator review case/action loop.
- Confirms S65 builds on the closed S64 workbench projection and existing
  `ag_op_notes` / `ag_ev_exports` foundations.
- Confirms Slice 0641 adds no database table.
- Reserves the short candidate case table name `ag_op_cases`; the optional
  future action-event table name `ag_op_case_events` is checked for length but
  action history is deferred in favor of AG operational events first.
- Confirms case intake should start from safe workbench targets, existing
  operator-review issue candidates, note refs, and redacted evidence export
  refs.
- Confirms source AE/CX/MO/OA records remain read-only and raw payloads,
  provider material, storage paths, database URLs, service tokens, idempotency
  keys, and notification secrets must not enter case/action evidence.
- Confirms the planned order for Slice 0642 through Slice 0650.

## Decision

- `nex-ag` owns operator review case records and action state transitions.
- The first implementation step after this audit is an AG-owned case
  persistence foundation.
- Case actions are idempotent state transitions:
  `CREATE_CASE`, `ACKNOWLEDGE`, `ASSIGN`, `RESOLVE`, `DISMISS`, and `REOPEN`.
- Initial case statuses are `OPEN`, `ACKNOWLEDGED`, `ASSIGNED`, `RESOLVED`,
  `DISMISSED`, and `REOPENED`.
- Free-text case comments or resolutions must be stored as hash plus short
  preview only.
- Notification delivery and external incident-system sync remain deferred.
- PostgreSQL smoke evidence for the case/action path must use the real
  `nex_ag_test` database before the S65 closure.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_case_action_boundary_audit.py tests/test_ag_operator_review_case_action_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_case_action_boundary_audit.py -q --cov=run_ag_operator_review_case_action_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_case_action_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
ag_operator_review_case_action_boundary_audit=pass paths=16/16 tokens=17/17 token_groups=7/7 tables=4/4 boundary=ag_owned_operator_review_cases_actions case_table=ag_op_cases action_history=operational_events_first next=Slice_0642
```
