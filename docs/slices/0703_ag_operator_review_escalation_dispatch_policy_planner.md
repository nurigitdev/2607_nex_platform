# Slice 0703: AG operator review escalation dispatch policy planner

## Intent

Add the mock-first S71 dispatch policy planner that decides whether a persisted
operator review escalation should produce a dispatch outbox record.

## Scope

- Add `ag_operator_review_escalation_dispatch_policy.v1`.
- Add `ag_operator_review_escalation_dispatch_plan.v1`.
- Map escalation level to initial dispatch intent:
  `FOLLOW_UP -> NOTIFY_OWNER`, `ATTENTION -> NOTIFY_OPERATOR`, and
  `BLOCKED -> OPEN_INCIDENT`.
- Keep `OBSERVE`, terminal/snoozed/acknowledged statuses, non-initial intents,
  and non-`MOCK` channels blocked at plan time.
- Build a safe pending dispatch record through the Slice 0702 record builder
  when policy permits dispatch.
- Keep route wiring, state-machine execution, mock provider execution, and
  protected PostgreSQL smoke evidence deferred.

## Decision

S71 remains mock-first. The planner may create a safe `PENDING` dispatch record
candidate, but it must not call an external provider or enable live notification,
email, webhook, or incident delivery. The plan includes only safe refs, hashes,
bounded previews, ids, statuses, policy metadata, and redaction flags.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

`OperatorReviewCaseService.plan_escalation_dispatch(...)` now returns a
metadata-safe dispatch policy plan and, when permitted, a Slice 0702-compatible
pending dispatch record.
