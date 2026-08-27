# Slice 0396: AE Web Repaired Response Decision PostgreSQL Smoke Evidence

## Scope

Add protected smoke evidence that the AE Web repaired response decision UX
wiring reaches the AE API decision route and persists into the `nex_ae_test`
database when explicitly enabled.

## Changes

- Added
  `scripts/smoke/run_ae_web_repaired_response_decision_postgres_smoke.py`.
- Added
  `tests/test_ae_web_repaired_response_decision_postgres_smoke.py`.
- Registered the protected smoke runner in `scripts/quality/run_quality_gate.sh`.
- The smoke validates AE Web decision wiring anchors before delegating to the
  persisted AE decision smoke, which runs migration, handoff insert, route
  create/list/detail, store read, row observation, and cleanup.

## Notes

The runner is protected by
`NEX_AE_WEB_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE=1`; without the flag it is
skipped in the standard regression gate. When enabled, it is restricted to the
`test` profile and uses `NEX_AE_TEST_DATABASE_URL`.

Evidence redacts the raw database URL and rejects database password leakage.

## Evidence

Targeted runner regression:

```text
./.venv/bin/pytest tests/test_ae_web_repaired_response_decision_postgres_smoke.py -q --cov=run_ae_web_repaired_response_decision_postgres_smoke --cov-branch --cov-report=term-missing
14 passed, 1 warning
run_ae_web_repaired_response_decision_postgres_smoke.py statement_coverage=100% branch_coverage=100%
```

Default protected smoke:

```text
./.venv/bin/python scripts/smoke/run_ae_web_repaired_response_decision_postgres_smoke.py --summary
ae_web_repaired_response_decision_postgres_smoke=skipped reason=NEX_AE_WEB_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE
```

Actual PostgreSQL test DB smoke:

```text
NEX_AE_WEB_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<redacted> ./.venv/bin/python scripts/smoke/run_ae_web_repaired_response_decision_postgres_smoke.py --summary
ae_web_repaired_response_decision_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL handoff_id=4e7a782a-45ac-53d6-a725-ea4d1db55ca2 decision_id=e6e3461e-d7ef-561a-8938-9152fc0cdd5a row_count=1 web_anchors=24/24 deleted_decisions=1 deleted_handoffs=1
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2868 passed, 1 warning
statement_coverage=98.69%
branch_coverage=96.14%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
ae_web_repaired_response_decision_postgres_smoke=skipped reason=NEX_AE_WEB_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE
```
