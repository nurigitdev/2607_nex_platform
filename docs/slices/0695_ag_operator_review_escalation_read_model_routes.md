# Slice 0695: AG operator review escalation read-model routes

## Intent

Expose persisted S70 escalation state as a protected AG read model.

## Scope

- Add `ag_operator_review_escalation_list.v1`.
- Add `OperatorReviewCaseService.list_escalations`.
- Add protected `GET /admin/v1/operator-review/escalations`.
- Add protected `GET /admin/v1/operator-review/escalations/{escalation_id}`.
- Support filters for case, candidate, status, and target refs.
- Keep raw comments, notification payloads, external incident payloads, and raw
  idempotency keys out of list/detail responses.

## Decision

The persisted escalation read model is separate from the S69 generated
candidate projection. The list/detail API reads only `ag_op_escalations` state,
which makes operator action state visible without rematerializing candidates or
triggering outbound integrations.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

The persisted escalation list/detail routes are protected, filterable, and safe
for operator-facing read-model use.
