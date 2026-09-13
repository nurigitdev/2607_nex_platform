# Slice 0693: AG operator review escalation action state machine

## Intent

Add the AG-owned escalation action state machine on top of the Slice 0692
`ag_op_escalations` persistence foundation.

## Scope

- Add escalation action schema and mutation response constants.
- Define supported escalation actions: acknowledge, snooze, dismiss, resolve,
  and reopen.
- Add safe action record construction with comment hashes/previews and
  idempotency-key hashes only.
- Add deterministic state transitions from active/reopened/snoozed states to
  terminal or operator-held states.
- Add safe operational-event emission for escalation actions.
- Keep notification delivery and external incident sync deferred.

## Decision

Escalation action state remains AG-owned and stores only the safe read-model
state needed by operators. Raw comments, notification payloads, external
incident payloads, provider payloads, source text, and raw idempotency keys are
not stored or returned. Route wiring is intentionally left to the next Slice so
the transition rules are regression-tested before exposing the mutation API.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

The escalation action state machine supports safe ACKNOWLEDGE, SNOOZE,
DISMISS, RESOLVE, and REOPEN actions without introducing outbound integration
side effects.
