# Slice 0709: AG operator review escalation dispatch privacy regression

## Intent

Add a repeatable privacy regression pack for the S71 escalation dispatch outbox
surface.

## Scope

- Add an in-memory protected smoke script for dispatch plan creation, dispatch
  list/detail reads, dispatch action mutation, operations dashboard visibility,
  and issue-candidate visibility.
- Verify that raw provider payloads, notification payloads, external incident
  payloads, raw action comments, raw prompts, raw source text, storage paths,
  provider keys, service tokens, database URLs, and raw idempotency keys do not
  appear in public route payloads or smoke evidence.
- Verify that sensitive create/action payloads are rejected by the shared AG
  operator-review redaction guard.
- Wire the regression pack into `scripts/quality/run_quality_gate.sh`.

## Decision

S71 privacy regression stays mock-first and in-memory. PostgreSQL persistence
evidence is reserved for Slice 0710 so the privacy surface can run quickly in
every full quality gate without requiring opt-in database smoke flags.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_privacy_regression.py -q --cov=run_ag_operator_review_escalation_dispatch_privacy_regression --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_privacy_regression.py --summary
./scripts/quality/run_quality_gate.sh
```

## Result

AG now has a permanent regression guard for S71 dispatch route and operations
surfaces before the PostgreSQL smoke layer is added.
