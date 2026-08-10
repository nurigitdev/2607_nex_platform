# Slice 0204: CX Upload Duplicate/Upsert PostgreSQL Smoke Hardening

## Scope

Slice 0204 adds protected PostgreSQL smoke coverage for CX upload duplicate and
source-file reuse behavior.

Implemented:

- `scripts/smoke/run_cx_upload_duplicate_postgres_smoke.py`
  - disabled by default
  - only allows the `test` profile
  - runs CX migrations before execution
  - uploads the same source for one owner twice
  - verifies the duplicate upload returns `ALREADY_EXISTS` and reuses the
    existing document id
  - uploads the same source for another owner
  - verifies the other owner gets a distinct document id while sharing the same
    `cx_source_files` row
  - verifies active content and owner ACL row counts in PostgreSQL
  - cleans up smoke rows after execution without deleting a shared source file
    until all referencing smoke content rows are removed
- `scripts/smoke/run_postgres_test_smoke_suite.py` now includes the
  `cx_upload_duplicate` stage after `cx_upload_ownership`.
- `scripts/quality/run_quality_gate.sh` runs the new smoke in default guarded
  mode.

## Guard

The protected smoke requires:

```text
NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE=1
NEX_CX_TEST_DATABASE_URL=<test database URL>
```

Optional profile override:

```text
NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE_PROFILE=test
```

Any non-test profile fails before writes.

## PostgreSQL Evidence

The smoke was executed against the real `nex_cx_test` database on localhost.
The stored database URL is redacted in evidence:

```text
postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test
```

Observed protected summary:

```text
cx_upload_duplicate_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
```

Observed protected JSON checks:

```text
status=PASS
profile=test
runtime_mode=true
first_upload_created=true
duplicate_upload_reused=true
duplicate_document_id_reused=true
duplicate_existing_document_reported=true
other_owner_created=true
other_owner_document_distinct=true
source_file_reused_across_owners=true
same_owner_active_content_count=true
other_owner_active_content_count=true
source_file_count=true
active_content_count=true
owner_acl_count=true
raw_payload_absent=true
```

Default quality-gate smoke path:

```text
cx_upload_duplicate_postgres_smoke=skipped reason=NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE
```

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_nex_cx_ingestion.py tests/test_nex_cx_repository.py -q
```

Protected PostgreSQL smoke:

```bash
NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='<redacted test DB URL>' \
./.venv/bin/python scripts/smoke/run_cx_upload_duplicate_postgres_smoke.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
379 passed
```

Observed full quality gate:

```text
1581 passed
statement_coverage=97.90%
branch_coverage=93.56%
contract_validation=pass schemas=45 examples=74 negative_examples=50 openapi=7
```
