# Slice 0644: AG Operator Review Case Action State Machine

Slice 0644 adds the internal AG case-action state machine.

## Scope

- Adds safe case action records for `ACKNOWLEDGE`, `ASSIGN`, `RESOLVE`,
  `DISMISS`, and `REOPEN`.
- Adds transition validation from current case status to the requested target
  status.
- Adds idempotent action execution in `OperatorReviewCaseService.apply_action`.
- Stores only the latest safe action summary on the case metadata while keeping
  action history operational-event-first.
- Keeps route wiring, dashboard correlation, contract freeze, and PostgreSQL
  smoke evidence deferred to later S65 slices.

## Decision

- `CREATE_CASE` remains represented by `POST /admin/v1/operator-review/cases`;
  it is not accepted as an action against an existing case.
- `ASSIGN` requires `assignment_ref.assignee_type` and
  `assignment_ref.assignee_id`.
- `RESOLVE` and `DISMISS` require either `resolution_comment` or
  `action_comment`; only hash plus bounded preview is stored.
- `REOPEN` clears `closed_at` but preserves prior safe resolution metadata.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
