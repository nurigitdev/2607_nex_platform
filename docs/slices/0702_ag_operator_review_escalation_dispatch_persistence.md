# Slice 0702: AG operator review escalation dispatch persistence foundation

## Intent

Add the AG-owned safe dispatch/outbox persistence foundation for S71 escalation
outbound dispatch work.

## Scope

- Add
  `database/nex-ag/migrations/0702_ag_operator_review_escalation_dispatch.sql`.
- Create the short table `ag_op_esc_dispatches`.
- Add in-memory and SQLAlchemy-backed dispatch stores.
- Add safe dispatch record construction from persisted S70 escalation state.
- Persist only safe dispatch metadata: refs, status fields, hashes, bounded
  previews, attempt counters, and retry timestamps.
- Keep dispatch planning, state-machine execution, route wiring, provider
  adapters, and live delivery deferred to later S71 slices.

## Decision

`ag_op_esc_dispatches` is the S71 outbox table for escalation dispatch intent
and attempt state. It references `ag_op_escalations` and `ag_op_cases`, while
`service_operational_events` remains the safe action history surface. Raw
notification bodies, external incident payloads, provider secrets, database
URLs, service tokens, raw source text, raw operator comments, and raw
idempotency keys are not stored.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

The dispatch persistence foundation stores S71 outbound dispatch state through
`OperatorReviewEscalationDispatchStore` and
`SqlAlchemyOperatorReviewEscalationDispatchStore`, uses the reserved
`ag_op_esc_dispatches` table, and keeps branch coverage above the current
project threshold.
