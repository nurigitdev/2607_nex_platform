# Slice 0692: AG operator review escalation persistence foundation

## Intent

Add the AG-owned persistence foundation for the S70 escalation action loop.

## Scope

- Add `database/nex-ag/migrations/0692_ag_operator_review_escalation_persistence.sql`.
- Create the short table `ag_op_escalations`.
- Add in-memory and SQLAlchemy stores for escalation records.
- Add safe escalation record construction from S69 escalation candidates.
- Persist only safe operator acknowledgement/action state: hashes, bounded
  previews, refs, state fields, and metadata flags.
- Keep outbound notification delivery and external incident sync deferred.

## Decision

`ag_op_escalations` is the S70 table for acknowledgement, snooze, dismissal,
resolution, and reopened escalation state. `ag_op_cases` remains the case state
source of record, while `service_operational_events` remains the safe action
history source. Raw comments, notification payloads, external incident payloads,
provider payloads, source text, database URLs, service tokens, and raw
idempotency keys are not stored.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

The persistence foundation stores escalation state through
`OperatorReviewEscalationStore` and `SqlAlchemyOperatorReviewEscalationStore`,
uses `ag_op_escalations`, and keeps branch coverage above the current project
threshold.
