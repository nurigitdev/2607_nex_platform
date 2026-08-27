# Slice 0389: AE Repaired Handoff Decision PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for repaired response user decisions.

The smoke uses the AE test profile only. It applies current `nex-ae-api`
migrations, creates a repaired response handoff in the real AE test DB, submits
a decision through the AE API route, reads it back through list/detail routes,
checks table/index/JSONB observations, and cleans up the inserted rows.

## Implemented

- Added `scripts/smoke/run_ae_repaired_response_decision_postgres_smoke.py`.
- Added protected flag `NEX_AE_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE=1`.
- Enforced test-profile execution with
  `NEX_AE_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE_PROFILE=test`.
- Verified migration record `0387_ae_repaired_response_decision_persistence`.
- Verified `ae_repaired_response_decisions` row persistence, JSONB storage
  fields, expected indexes, selected generation semantics, and cleanup.
- Registered the protected smoke in `scripts/quality/run_quality_gate.sh` with
  default skip behavior.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_ae_repaired_response_decision_postgres_smoke.py -q --cov=run_ae_repaired_response_decision_postgres_smoke --cov-branch --cov-report=term-missing
16 passed, 1 warning in 2.37s
run_ae_repaired_response_decision_postgres_smoke.py statement_coverage=100% branch_coverage=100%
```

Protected PostgreSQL smoke against `nex_ae_test`:

```text
NEX_AE_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<redacted> ./.venv/bin/python scripts/smoke/run_ae_repaired_response_decision_postgres_smoke.py --summary
ae_repaired_response_decision_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL handoff_id=33a2d1b7-3193-5453-84f0-ae4af924a1b8 decision_id=23f7912d-64ea-52f8-bd3d-5fe76c877618 row_count=1 deleted_decisions=1 deleted_handoffs=1
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2847 passed, 1 warning in 111.40s
statement_coverage=98.68% threshold=95.00%
branch_coverage=96.13% threshold=85.00%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
ae_repaired_response_decision_postgres_smoke=skipped reason=NEX_AE_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE
```

Recommended next slice:

```text
Slice 0390: S39 repaired response handoff closure checkpoint
```
