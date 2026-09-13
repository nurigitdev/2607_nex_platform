# Slice 0706: AG operator review escalation dispatch read-model routes

## Intent

Expose the S71 dispatch outbox as a protected AG read model so operators can
inspect safe dispatch state before any live provider execution is introduced.

## Scope

- Add `ag_operator_review_escalation_dispatch_list.v1`.
- Add `OperatorReviewCaseService.list_escalation_dispatches(...)`.
- Add protected `GET /admin/v1/operator-review/dispatches`.
- Support safe filters for escalation id, case id, dispatch status, dispatch
  intent, channel type, target ref, and limit.
- Return count/status/intent/channel summaries and route path metadata.

## Decision

The list route returns the same safe outbox records introduced in Slice 0702 and
updated by Slice 0704/0705. It does not expose raw notification payloads,
external incident payloads, provider secrets, raw comments, source text,
database URLs, service tokens, or raw idempotency keys.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

S71 now has protected dispatch list/read-model access with safe filtering and
summary metadata.
