# Slice 0694: AG operator review escalation action route wiring

## Intent

Expose the Slice 0693 escalation action state machine through a protected AG
operator API.

## Scope

- Add escalation store injection to `register_operator_review_case_routes`.
- Add `OperatorReviewCaseService.get_escalation`.
- Add `OperatorReviewCaseService.apply_escalation_action`.
- Add protected `POST /admin/v1/operator-review/escalations/{escalation_id}/actions`.
- Preserve idempotent replay and conflict semantics.
- Emit safe operational events for new escalation actions only.

## Decision

The route acts only on records already persisted in `ag_op_escalations`.
Materializing S69 escalation candidates into persisted escalation records stays
separate. This keeps the mutation boundary small: API callers can acknowledge,
snooze, dismiss, resolve, or reopen an existing AG-owned escalation without
triggering notification delivery or external incident sync.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

The protected escalation action route supports new mutations, idempotent
replays, conflict detection, missing escalation errors, and safe event emission.
