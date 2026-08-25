# Slice 0345: AG Generation Remediation PostgreSQL Smoke Evidence

## Scope

Persist AG generation remediation tasks in PostgreSQL and provide protected
smoke evidence against the real `nex_ag_test` database.

## Implemented

- Added the `0345_ag_generation_remediation_task_persistence` migration.
- Created `ag_generation_remediation_tasks` with:
  - `remediation_action_id` primary key;
  - owner columns split for indexed lookup;
  - JSONB columns for owner refs, reason codes, source refs, evidence,
    optional result refs, and metadata;
  - generation, status, action type, and owner time indexes.
- Added `scripts/smoke/run_ag_generation_remediation_postgres_smoke.py`.
- Wired the new smoke runner into the full quality gate.
- Hardened remediation repository parameter mapping so absent `result_ref`
  persists as SQL `NULL`, while completed repair results still round-trip as
  JSONB objects.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_ag_generation_remediation_postgres_smoke.py tests/test_nex_ag_generation_remediation.py -q
54 passed
```

Migration regression:

```text
./.venv/bin/pytest tests/test_db_migration_runner.py tests/test_database_schema_foundation.py -q
35 passed
```

Default smoke boundary:

```text
./.venv/bin/python scripts/smoke/run_ag_generation_remediation_postgres_smoke.py --summary
ag_generation_remediation_postgres_smoke=skipped reason=NEX_AG_GENERATION_REMEDIATION_POSTGRES_SMOKE
```

PostgreSQL test DB smoke:

```text
NEX_AG_GENERATION_REMEDIATION_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test \
./.venv/bin/python scripts/smoke/run_ag_generation_remediation_postgres_smoke.py --summary
ag_generation_remediation_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL remediation_action_id=ag-remediation-smoke-2bac1ee3caa3 row_count=1 deleted_rows=1
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2387 passed, 1 warning
statement_coverage=98.53% threshold=95.00%
branch_coverage=95.66% threshold=85.00%
contract_validation=pass schemas=56 examples=88 negative_examples=65 openapi=7
ag_generation_remediation_postgres_smoke=skipped reason=NEX_AG_GENERATION_REMEDIATION_POSTGRES_SMOKE
```

Next slice:

```text
Slice 0346: AG remediation operations dashboard projection
```
