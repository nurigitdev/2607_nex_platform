# Slice 0679: AG operator review case lifecycle PostgreSQL smoke evidence

## Intent

Prove the S68 operator review case lifecycle read models against the real
`nex_ag_test` PostgreSQL database.

## Scope

- Add `scripts/smoke/run_ag_operator_review_case_lifecycle_postgres_smoke.py`.
- Keep the smoke protected by
  `NEX_AG_OPERATOR_REVIEW_CASE_LIFECYCLE_POSTGRES_SMOKE=1`.
- Run AG test migrations before the smoke.
- Create a case, persist note/export evidence, apply a terminal action, and read
  the closure packet route.
- Verify timeline/action outcome/workload read models over PostgreSQL-backed
  stores.
- Observe `ag_op_cases`, `ag_op_notes`, `ag_ev_exports`, and
  `service_operational_events` rows directly in the test DB.
- Clean up smoke rows after execution.

## Decision

The smoke does not add a lifecycle persistence table. It confirms the S68
lifecycle path still derives from existing AG-owned tables and operational
events. The default quality gate runs the smoke in skipped mode unless the
explicit opt-in environment variable is set.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_case_lifecycle_postgres_smoke.py tests/test_ag_operator_review_case_lifecycle_postgres_smoke.py
PYTHONPATH=scripts/smoke:services/_shared:services/nex-ag:scripts/db ./.venv/bin/pytest tests/test_ag_operator_review_case_lifecycle_postgres_smoke.py -q --cov=run_ag_operator_review_case_lifecycle_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AG_OPERATOR_REVIEW_CASE_LIFECYCLE_POSTGRES_SMOKE=1 NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test ./.venv/bin/python scripts/smoke/run_ag_operator_review_case_lifecycle_postgres_smoke.py --summary
```

## Expected Summary

```text
ag_operator_review_case_lifecycle_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL ...
```
