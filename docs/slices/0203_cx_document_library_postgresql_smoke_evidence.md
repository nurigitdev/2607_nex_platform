# Slice 0203: CX Document Library PostgreSQL Smoke Evidence

## Scope

Slice 0203 adds protected PostgreSQL smoke evidence for the Slice 0202 CX
document library API.

Implemented:

- `scripts/smoke/run_cx_document_library_postgres_smoke.py`
  - disabled by default
  - only allows the `test` profile
  - runs CX migrations before execution
  - uploads two documents for different owners through the CX upload API
  - lists `/api/v1/documents` for one owner through the CX document library API
  - verifies owner scope, source metadata, PostgreSQL runtime mode, and raw-safe
    response boundaries
  - cleans up smoke rows after execution
- `scripts/smoke/run_postgres_test_smoke_suite.py` now includes the
  `cx_document_library` stage after `cx_upload_ownership`.
- `scripts/quality/run_quality_gate.sh` runs the new smoke in default guarded
  mode, so normal regression records a skip unless the guard env is enabled.
- SQLite regression fixtures now include empty document summary, summary
  embedding, and processing read-model tables for the document library smoke.

## Guard

The protected smoke requires:

```text
NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE=1
NEX_CX_TEST_DATABASE_URL=<test database URL>
```

Optional profile override:

```text
NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE_PROFILE=test
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
cx_document_library_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
```

Observed protected JSON checks:

```text
status=PASS
profile=test
returned_count=1
runtime_mode=true
api_upload_status_created=true
list_status_ok=true
source_metadata_uses_test_db=true
projection_schema_version=true
owner_scope_filtered=true
other_owner_excluded=true
persisted_owner_a_count=true
persisted_owner_b_count=true
raw_payload_absent=true
```

Default quality-gate smoke path:

```text
cx_document_library_postgres_smoke=skipped reason=NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE
```

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_nex_cx_document_library.py -q
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
164 passed
```

Observed full quality gate:

```text
1574 passed
statement_coverage=97.88%
branch_coverage=93.53%
contract_validation=pass schemas=45 examples=74 negative_examples=50 openapi=7
```
