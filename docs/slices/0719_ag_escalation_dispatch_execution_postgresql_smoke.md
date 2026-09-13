# Slice 0719: AG escalation dispatch execution PostgreSQL smoke evidence

## Intent

Prove the S72 dispatch execution worker against the real AG PostgreSQL test
database, including state transition, safe result metadata persistence, and
operations dashboard visibility.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_postgres_smoke.py`.
- The smoke is protected by
  `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_EXECUTION_POSTGRES_SMOKE=1` and
  reads `NEX_AG_TEST_DATABASE_URL`.
- The smoke runs `nex-ag` migrations first, writes one case, escalation, and
  dispatch into `nex_ag_test`, executes
  `run_dispatch_execution_worker_once(...)`, verifies `SUCCEEDED` dispatch
  state and `metadata.last_execution_result`, checks the AG operations
  dashboard `execution_summary`, directly observes PostgreSQL rows, and cleans
  up smoke rows.
- The quality gate now invokes the smoke in skipped mode by default.

## Boundary

Slice 0719 does not enable live notification delivery or external incident
dispatch. The PostgreSQL smoke uses the mock dispatch execution provider and
persists only safe status/hash/preview metadata.

## Evidence

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_execution_postgres_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_execution_postgres_smoke --cov-branch --cov-report=term-missing
```

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_EXECUTION_POSTGRES_SMOKE=1 NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_postgres_smoke.py --summary
```
