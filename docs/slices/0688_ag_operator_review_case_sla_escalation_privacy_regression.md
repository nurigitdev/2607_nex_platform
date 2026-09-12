# Slice 0688: AG operator review case SLA/escalation privacy regression pack

## Intent

Add an automated privacy regression pack for the S69 SLA policy, aging,
escalation, and dashboard surfaces.

## Scope

- Add `run_ag_operator_review_case_sla_escalation_privacy_regression.py`.
- Seed an in-memory AG case store with deliberately unsafe raw comments,
  prompts, provider keys, database URL, service token, storage path, notification
  payload, and external incident payload values.
- Exercise `/sla-policy`, `/aging`, `/escalations`, and the operations
  dashboard through authenticated routes.
- Assert forbidden values and forbidden raw keys do not appear in returned
  payloads or evidence.
- Add the privacy smoke to `scripts/quality/run_quality_gate.sh`.

## Decision

S69 privacy validation remains mock-first and route-surface based. PostgreSQL
evidence is deferred to the next Slice so the privacy pack can run quickly in
every regression gate.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_case_sla_escalation_privacy_regression.py -q --cov=run_ag_operator_review_case_sla_escalation_privacy_regression --cov-branch --cov-report=term-missing
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_case_sla_escalation_privacy_regression.py --summary
```

## Result

The targeted tests cover the privacy smoke, recursive forbidden-key checks,
redaction flag checks, dashboard guard checks, redacted evidence guard, and CLI
summary output with 100% statement and branch coverage for the new script.
