# Slice 0705: AG operator review escalation dispatch route wiring

## Intent

Expose protected AG API routes for the S71 escalation dispatch outbox while
keeping provider execution deferred and mock-first.

## Scope

- Add protected dispatch creation at
  `/admin/v1/operator-review/escalations/{escalation_id}/dispatches`.
- Require `Idempotency-Key` for persisted dispatch creation.
- Replay same-key/same-payload dispatch creation and reject same-key/different
  payload with a conflict.
- Add protected dispatch detail at
  `/admin/v1/operator-review/dispatches/{dispatch_id}`.
- Add protected dispatch action application at
  `/admin/v1/operator-review/dispatches/{dispatch_id}/actions`.
- Emit safe operational events for dispatch creation and dispatch actions.

## Decision

The routes persist only the safe outbox record and state-machine fields. They do
not execute notification providers, incident providers, or live external
delivery. Raw provider payloads, service tokens, database URLs, raw comments,
raw bodies, and raw idempotency keys remain excluded from API responses,
persistence, and operational events.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

S71 now has protected route wiring for safe dispatch creation, detail reads, and
state-machine action application.
