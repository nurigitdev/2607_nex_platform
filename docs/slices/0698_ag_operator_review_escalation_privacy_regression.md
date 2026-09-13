# Slice 0698: AG operator review escalation privacy regression pack

## Intent

Add a mock-first privacy regression pack for the persisted S70 escalation list,
detail, action, dashboard, and issue-candidate surfaces.

## Scope

- Add `run_ag_operator_review_escalation_privacy_regression.py`.
- Seed an in-memory AG escalation store with safe persisted action state derived
  from an escalation candidate and secret idempotency keys.
- Exercise escalation list/detail routes, the operations dashboard,
  issue-candidates, and the escalation action route.
- Assert forbidden raw values, forbidden raw keys, and unsafe redaction flags do
  not appear in returned payloads or evidence.
- Prove sensitive action payload ingress is rejected before persistence.
- Add the privacy smoke to `scripts/quality/run_quality_gate.sh`.

## Decision

S70 privacy validation remains mock-first and route-surface based. PostgreSQL
evidence is left for Slice 0699 so this regression can run quickly in every
quality gate while still covering the persisted escalation action contract.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_privacy_regression.py -q --cov=run_ag_operator_review_escalation_privacy_regression --cov-branch --cov-report=term-missing
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_privacy_regression.py --summary
./scripts/quality/run_quality_gate.sh
```

## Result

The regression covers S70 escalation list, detail, action mutation, dashboard,
issue-candidate, redaction-flag, forbidden-key, evidence-redaction, CLI, and
sensitive ingress rejection paths without exposing raw action comments,
notification payloads, external incident payloads, database URLs, tokens,
storage paths, or idempotency keys.
