# Slice 0334: AE Generation Feedback PostgreSQL Smoke Evidence

## Scope

Persist AE generation feedback and prove the route backing store against the
actual `nex_ae_test` PostgreSQL database.

## Implemented

- Added migration `0334_ae_generation_feedback_persistence`.
- Added table `ae_generation_feedback` with indexed columns for:
  - `tenant_id`, `user_id`, and `created_at`;
  - `interaction_id`;
  - `cx_generation_id`.
- Stored flexible fields as PostgreSQL `JSONB`:
  - `feedback_reasons`;
  - `quality_issue_refs`;
  - `metadata`.
- Added `SqlAlchemyGenerationFeedbackStore` with save/get/list/delete support.
- Wired AE default feedback store to use the service persistence session factory
  when the app runs in PostgreSQL persistence mode.
- Added optional smoke runner:
  - `scripts/smoke/run_ae_generation_feedback_postgres_smoke.py`.
- Registered the skipped-by-default runner in the full quality gate.
- Added regression coverage for SQLite store round-trip and smoke runner
  skip/failure/success evidence paths.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_generation_feedback.py tests/test_ae_generation_feedback_postgres_smoke.py -q
43 passed, 1 warning
```

Default protected smoke:

```text
./.venv/bin/python scripts/smoke/run_ae_generation_feedback_postgres_smoke.py --summary
ae_generation_feedback_postgres_smoke=skipped reason=NEX_AE_GENERATION_FEEDBACK_POSTGRES_SMOKE
```

Actual `nex_ae_test` PostgreSQL smoke:

```text
NEX_AE_GENERATION_FEEDBACK_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' \
./.venv/bin/python scripts/smoke/run_ae_generation_feedback_postgres_smoke.py --summary

ae_generation_feedback_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL feedback_id=ae-feedback-smoke-94b1ee96add8 row_count=1 deleted_rows=1
```

The smoke applies or verifies the AE test migrations before writing the smoke
row, confirms the JSON fields are `jsonb`, reads the feedback back through the
SQLAlchemy store, lists it by interaction id, and deletes the row during cleanup.

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2261 passed, 1 warning
statement_coverage=98.54%
branch_coverage=95.53%
contract_validation=pass schemas=53 examples=85 negative_examples=62 openapi=7
```
