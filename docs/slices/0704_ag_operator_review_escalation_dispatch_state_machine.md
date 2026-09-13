# Slice 0704: AG operator review escalation dispatch state machine

## Intent

Add the AG-owned dispatch state machine for safe S71 outbox execution tracking.

## Scope

- Add `ag_operator_review_escalation_dispatch_action.v1`.
- Add `ag_operator_review_escalation_dispatch_action_mutation.v1`.
- Support deterministic dispatch actions:
  `START`, `SUCCEED`, `FAIL`, `RETRY`, and `CANCEL`.
- Freeze allowed transitions:
  `PENDING/RETRY_WAIT -> DISPATCHING`, `DISPATCHING -> SUCCEEDED/FAILED`,
  `FAILED -> RETRY_WAIT`, and `PENDING/RETRY_WAIT/FAILED -> CANCELLED`.
- Update only safe dispatch state fields, attempt counters, timestamps, safe
  error hashes, and metadata flags.
- Keep provider execution, route wiring, operational event emission, and
  protected PostgreSQL smoke evidence deferred.

## Decision

The dispatch state machine records provider execution state without performing
provider execution. Raw provider payloads, notification bodies, incident
payloads, provider errors, service tokens, database URLs, storage paths, and
raw idempotency keys remain excluded from action records and mutation
responses.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

`apply_operator_review_escalation_dispatch_action(...)` and
`OperatorReviewCaseService.apply_escalation_dispatch_action(...)` now provide a
metadata-safe state-machine foundation for S71 dispatch execution.
