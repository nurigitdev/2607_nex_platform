# Slice 0399: AE Web Repaired Response Review Diagnostics PostgreSQL Smoke

## Scope

Add protected smoke evidence that the repaired response review diagnostics
surface remains connected while the repaired response decision path writes to
the real AE test database.

## Changes

- Added
  `scripts/smoke/run_ae_web_repaired_response_review_diagnostics_postgres_smoke.py`.
- Added
  `tests/test_ae_web_repaired_response_review_diagnostics_postgres_smoke.py`.
- Registered the protected smoke runner in `scripts/quality/run_quality_gate.sh`.
- The runner validates AE Web diagnostics/read-model anchors before delegating
  to the repaired response decision PostgreSQL smoke, which performs migration,
  handoff insert, decision route create/list/detail, store read, row observation,
  and cleanup against `nex_ae_test` when explicitly enabled.

## Notes

The runner is protected by
`NEX_AE_WEB_REPAIRED_RESPONSE_REVIEW_DIAGNOSTICS_POSTGRES_SMOKE=1`; without the
flag it is skipped in the standard regression gate. When enabled, it is
restricted to the `test` profile and uses `NEX_AE_TEST_DATABASE_URL`.

Evidence redacts the raw database URL and rejects database password leakage.

## Evidence

Targeted runner regression:

```text
./.venv/bin/pytest tests/test_ae_web_repaired_response_review_diagnostics_postgres_smoke.py -q --cov=run_ae_web_repaired_response_review_diagnostics_postgres_smoke --cov-branch --cov-report=term-missing
16 passed, 1 warning
run_ae_web_repaired_response_review_diagnostics_postgres_smoke.py statement_coverage=100% branch_coverage=100%
```

Default protected smoke:

```text
./.venv/bin/python scripts/smoke/run_ae_web_repaired_response_review_diagnostics_postgres_smoke.py --summary
ae_web_repaired_response_review_diagnostics_postgres_smoke=skipped reason=NEX_AE_WEB_REPAIRED_RESPONSE_REVIEW_DIAGNOSTICS_POSTGRES_SMOKE
```

Actual PostgreSQL test DB smoke:

```text
NEX_AE_WEB_REPAIRED_RESPONSE_REVIEW_DIAGNOSTICS_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<redacted> ./.venv/bin/python scripts/smoke/run_ae_web_repaired_response_review_diagnostics_postgres_smoke.py --summary
ae_web_repaired_response_review_diagnostics_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL decision_id=63f8489c-3bd9-5bac-b704-41cdfaa6e88f row_count=1 diagnostics_anchors=15/15 deleted_decisions=1 deleted_handoffs=1
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2885 passed, 1 warning
statement_coverage=98.69%
branch_coverage=96.15%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
ae_web_repaired_response_review_diagnostics_postgres_smoke=skipped reason=NEX_AE_WEB_REPAIRED_RESPONSE_REVIEW_DIAGNOSTICS_POSTGRES_SMOKE
```
