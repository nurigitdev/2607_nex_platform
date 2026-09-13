# Slice 0699: AG operator review escalation PostgreSQL smoke evidence

## Intent

Add protected PostgreSQL smoke evidence for the persisted S70 escalation action
loop.

## Scope

- Add `run_ag_operator_review_escalation_postgres_smoke.py`.
- Guard live execution behind
  `NEX_AG_OPERATOR_REVIEW_ESCALATION_POSTGRES_SMOKE=1`.
- Run `nex-ag` migrations against the configured test database.
- Seed one persisted escalation in `ag_op_escalations`.
- Read escalation list/detail, the operations dashboard, and issue-candidates.
- Apply and replay an ACKNOWLEDGE action through the protected escalation action
  route.
- Observe `ag_op_escalations` and `service_operational_events` directly.
- Cleanup smoke escalation and event rows after execution.

## Decision

S70 uses the short `ag_op_escalations` table introduced in Slice 0692 and keeps
action history in `service_operational_events`. The smoke verifies persisted
state and audit event linkage while keeping raw idempotency keys and raw action
comments out of evidence and database-observed payloads.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_postgres_smoke.py -q --cov=run_ag_operator_review_escalation_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AG_OPERATOR_REVIEW_ESCALATION_POSTGRES_SMOKE=1 NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test' PYTHONPATH=services/_shared:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```

## Result

The targeted tests cover skip, missing DB URL, migration failure, execution
failure, DB observation, cleanup, evidence redaction, CLI output, and mocked
success/failure paths. The protected smoke was also executed against
`nex_ag_test`, persisted one case and one escalation, applied one action event,
verified replay, read S70 projections, and cleaned up case, escalation, and
event rows.
