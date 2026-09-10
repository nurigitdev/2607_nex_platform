# Slice 0643: AG Operator Review Case Service/API Routes

Slice 0643 wires the AG-owned operator review case persistence foundation into
protected admin routes.

## Scope

- Adds `OperatorReviewCaseService` with idempotent create, list, and detail
  lookup behavior.
- Adds protected AG routes:
  - `POST /admin/v1/operator-review/cases`
  - `GET /admin/v1/operator-review/cases`
  - `GET /admin/v1/operator-review/cases/{case_id}`
- Requires `Idempotency-Key` for case mutations and reports replay/conflict
  outcomes without storing the raw key.
- Emits safe operational events for newly recorded cases.
- Keeps explicit case action state-machine commands, dashboard correlation,
  contract freeze, and PostgreSQL smoke evidence deferred to later S65 slices.

## Decision

- AG service tokens and admin user tokens can read cases; only admin users can
  use user-token access.
- Caller-supplied `case_id` is ignored for idempotent create requests so the
  stored identity remains derived from target/operator/idempotency material.
- Case event details include target/status/priority/operator/assignee/hash
  metadata only; raw resolution comments and previews are not written to
  operational events.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py services/nex-ag/nex_ag/main.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
