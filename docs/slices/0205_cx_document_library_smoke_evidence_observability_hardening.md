# Slice 0205: CX Document Library Smoke Evidence Observability Hardening

## Scope

Slice 0205 hardens the CX document library PostgreSQL smoke evidence so the
output itself proves that the smoke ran against the test database and performed
write/read/cleanup work.

Implemented:

- `scripts/smoke/run_cx_document_library_postgres_smoke.py`
  - adds `migration` evidence with planned/applied/skipped counts
  - adds `db_observations` with owner-scoped persisted row counts and listed
    document ids
  - adds `cleanup_observations` with content/source row counts before and after
    cleanup
- regression tests now assert the formal migration and cleanup evidence shape.

## Evidence Shape

New PASS evidence fields:

```text
migration.service_id
migration.profile
migration.planned_count
migration.applied_count
migration.skipped_count
migration.dry_run
db_observations.owner_a_active_content_count
db_observations.owner_b_active_content_count
db_observations.listed_document_count
db_observations.listed_document_ids
cleanup_observations[].content_rows_before_delete
cleanup_observations[].content_rows_after_delete
cleanup_observations[].source_rows_before_delete
cleanup_observations[].source_rows_after_delete
```

## PostgreSQL Evidence

The smoke was executed against the real `nex_cx_test` database on localhost.
The stored database URL is redacted in evidence:

```text
postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test
```

Observed protected summary:

```text
cx_document_library_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
```

Observed protected JSON evidence:

```text
status=PASS
profile=test
migration.planned_count=12
migration.applied_count=0
migration.skipped_count=12
migration.dry_run=false
returned_count=1
db_observations.owner_a_active_content_count=1
db_observations.owner_b_active_content_count=1
db_observations.listed_document_count=1
cleanup_observations[0].content_rows_before_delete=1
cleanup_observations[0].content_rows_after_delete=0
cleanup_observations[0].source_rows_before_delete=1
cleanup_observations[0].source_rows_after_delete=0
cleanup_observations[1].content_rows_before_delete=1
cleanup_observations[1].content_rows_after_delete=0
cleanup_observations[1].source_rows_before_delete=1
cleanup_observations[1].source_rows_after_delete=0
```

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py -q
```

Protected PostgreSQL smoke:

```bash
NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='<redacted test DB URL>' \
./.venv/bin/python scripts/smoke/run_cx_document_library_postgres_smoke.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
160 passed
```

Observed full quality gate:

```text
1582 passed
statement_coverage=97.90%
branch_coverage=93.57%
contract_validation=pass schemas=45 examples=74 negative_examples=50 openapi=7
```
