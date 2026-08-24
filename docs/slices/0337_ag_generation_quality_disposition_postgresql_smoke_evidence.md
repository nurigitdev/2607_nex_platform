# Slice 0337: AG Generation Quality Disposition PostgreSQL Smoke Evidence

## Scope

Persist AG generation quality operator dispositions and prove the store against
the actual `nex_ag_test` PostgreSQL database.

## Implemented

- Added migration `0337_ag_generation_quality_operator_disposition_persistence`.
- Added table `ag_generation_quality_operator_dispositions` with indexed
  columns for:
  - `cx_generation_id` and `updated_at`;
  - `operator_type`, `operator_id`, and `updated_at`;
  - `disposition_status` and `updated_at`.
- Stored flexible fields as PostgreSQL `JSONB`:
  - `operator_ref`;
  - `reason_codes`;
  - `quality_issue_refs`;
  - `metadata`.
- Added `SqlAlchemyGenerationQualityDispositionStore` with save/get/list/delete
  support.
- Wired AG default disposition store to use service persistence when the app
  runs in PostgreSQL persistence mode.
- Added optional smoke runner:
  - `scripts/smoke/run_ag_generation_quality_disposition_postgres_smoke.py`.
- Registered the skipped-by-default runner in the full quality gate.
- Added SQLite regression coverage for the SQLAlchemy store and runner branch
  coverage for skip/failure/success/redaction paths.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_quality_disposition.py tests/test_ag_generation_quality_disposition_postgres_smoke.py -q
46 passed, 1 warning in 0.64s
```

Default protected smoke:

```text
./.venv/bin/python scripts/smoke/run_ag_generation_quality_disposition_postgres_smoke.py --summary
ag_generation_quality_disposition_postgres_smoke=skipped reason=NEX_AG_GENERATION_QUALITY_DISPOSITION_POSTGRES_SMOKE
```

Actual `nex_ag_test` PostgreSQL smoke:

```text
NEX_AG_GENERATION_QUALITY_DISPOSITION_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
./.venv/bin/python scripts/smoke/run_ag_generation_quality_disposition_postgres_smoke.py --summary

ag_generation_quality_disposition_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL disposition_id=ag-gq-disposition-smoke-92003c3ed64e row_count=1 deleted_rows=1
```

The smoke applies or verifies the AG test migrations before writing the smoke
row, confirms the JSON fields are `jsonb`, reads the disposition back through
the SQLAlchemy store, lists it by CX generation id, and deletes the row during
cleanup.
