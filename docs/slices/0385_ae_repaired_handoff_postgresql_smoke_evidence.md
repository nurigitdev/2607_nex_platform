# Slice 0385: AE Repaired Handoff PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for AE repaired response handoff
persistence against the real `nex_ae_test` database.

This slice keeps regression deterministic by default. The write smoke is guarded
by `NEX_AE_REPAIRED_RESPONSE_HANDOFF_POSTGRES_SMOKE=1` and requires the test
profile database URL in `NEX_AE_TEST_DATABASE_URL`.

## Implemented

- Added `scripts/smoke/run_ae_repaired_response_handoff_postgres_smoke.py`.
- The smoke runner:
  - refuses non-test profiles for write execution;
  - runs `nex-ae-api` service migrations against the test database;
  - inserts a sanitized repaired response handoff record through
    `SqlAlchemyRepairedResponseHandoffStore`;
  - selects by handoff id and interaction scope;
  - verifies JSONB column types, expected indexes, and the migration ledger;
  - deletes the smoke row and keeps raw database URLs out of evidence.
- Added the smoke runner to `scripts/quality/run_quality_gate.sh`; default gate
  execution reports a guarded skip unless the smoke env is enabled.
- Added regression tests for guard, config failure, migration failure, success
  redaction, execution failure, DB observation mapping, cleanup, and the
  store-backed smoke execution path.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_ae_repaired_response_handoff_postgres_smoke.py -q --cov=run_ae_repaired_response_handoff_postgres_smoke --cov-branch --cov-report=term-missing
15 passed in 1.03s
scripts/smoke/run_ae_repaired_response_handoff_postgres_smoke.py statement_coverage=100% branch_coverage=100%
```

Default guarded smoke:

```text
./.venv/bin/python scripts/smoke/run_ae_repaired_response_handoff_postgres_smoke.py --summary
ae_repaired_response_handoff_postgres_smoke=skipped reason=NEX_AE_REPAIRED_RESPONSE_HANDOFF_POSTGRES_SMOKE
```

Protected PostgreSQL smoke:

```text
NEX_AE_REPAIRED_RESPONSE_HANDOFF_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<redacted> ./.venv/bin/python scripts/smoke/run_ae_repaired_response_handoff_postgres_smoke.py
status=PASS service=nex-ae-api profile=test database_env=NEX_AE_TEST_DATABASE_URL
redacted_database_url=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test
migration_applied=["0383_ae_repaired_response_handoff_persistence"]
migration_skipped_count=9
table_present=true migration_recorded=true row_count=1
jsonb_columns=7/7 indexes_present=6/6 cleanup_deleted_rows=1
```

Protected PostgreSQL smoke summary refresh:

```text
NEX_AE_REPAIRED_RESPONSE_HANDOFF_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<redacted> ./.venv/bin/python scripts/smoke/run_ae_repaired_response_handoff_postgres_smoke.py --summary
ae_repaired_response_handoff_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL handoff_id=77c20a90-dff1-59a1-b813-d951d9703a4f row_count=1 deleted_rows=1
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2795 passed, 1 warning in 81.48s
statement_coverage=98.66%
branch_coverage=96.05%
contract_validation=pass schemas=60 examples=92 negative_examples=68 openapi=7
ae_repaired_response_handoff_postgres_smoke=skipped reason=NEX_AE_REPAIRED_RESPONSE_HANDOFF_POSTGRES_SMOKE
```

Recommended next slice:

```text
Slice 0386: AE repaired handoff user review surface/read-model planning
```
