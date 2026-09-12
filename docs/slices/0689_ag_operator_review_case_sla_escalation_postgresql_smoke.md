# Slice 0689: AG operator review case SLA/escalation PostgreSQL smoke evidence

## Intent

Add protected PostgreSQL smoke evidence for S69 SLA policy, aging, escalation,
and dashboard read models.

## Scope

- Add `run_ag_operator_review_case_sla_escalation_postgres_smoke.py`.
- Guard live execution behind
  `NEX_AG_OPERATOR_REVIEW_CASE_SLA_ESCALATION_POSTGRES_SMOKE=1`.
- Run `nex-ag` migrations against the configured test database.
- Create a smoke case through the protected AG route.
- Read back `/sla-policy`, `/aging`, `/escalations`, and the operations
  dashboard against the same persisted case.
- Observe `ag_op_cases` and `service_operational_events` directly.
- Cleanup smoke case and event rows after execution.

## Decision

The smoke uses the existing `ag_op_cases` and `service_operational_events`
tables. No S69-specific table is introduced because SLA/escalation is still a
read-model-first surface.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_case_sla_escalation_postgres_smoke.py -q --cov=run_ag_operator_review_case_sla_escalation_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AG_OPERATOR_REVIEW_CASE_SLA_ESCALATION_POSTGRES_SMOKE=1 NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test' PYTHONPATH=services/_shared:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_case_sla_escalation_postgres_smoke.py --summary
```

## Result

The targeted smoke tests cover skip, missing DB URL, migration failure, execution
failure, DB observation, cleanup, evidence redaction, CLI output, and mocked
success/failure paths with 100% statement and branch coverage. The protected
smoke was also executed against `nex_ag_test`, persisted one case and one event,
read the S69 projections, and cleaned up both rows.
