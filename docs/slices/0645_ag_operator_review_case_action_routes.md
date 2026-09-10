# Slice 0645: AG Operator Review Case Action Routes

Slice 0645 exposes the case-action state machine through a protected AG admin
route.

## Scope

- Adds `POST /admin/v1/operator-review/cases/{case_id}/actions`.
- Reuses AG operator-review auth and `Idempotency-Key` handling.
- Applies the Slice 0644 state machine through the existing case store.
- Emits a redaction-safe operational event for newly recorded actions.
- Keeps dashboard correlation, contract freeze, and PostgreSQL smoke evidence
  deferred to later S65 slices.

## Decision

- Action route replay returns `200`; new actions return `201`.
- Action events include target/status/operator/assignee/hash fields only.
- Replayed actions do not emit a second operational event.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
