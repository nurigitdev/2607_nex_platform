# Slice 0208: CX Document Detail PostgreSQL Smoke Evidence

## Scope

Slice 0208 adds opt-in PostgreSQL smoke evidence for the Slice 0207 document
detail API wiring.

Implemented:

- `scripts/smoke/run_cx_document_detail_postgres_smoke.py`
  - guarded by `NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE=1`
  - limited to `NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE_PROFILE=test`
  - runs CX migrations before execution
  - builds a PostgreSQL-backed CX FastAPI app
  - uploads a temporary document through the service API
  - reads `GET /api/v1/documents/{document_id}` with matching owner scope
  - verifies wrong-owner detail reads collapse to `cx.document_not_found`
  - verifies the detail projection reports `postgres-read` and the test DB env
  - verifies raw source and local storage paths do not appear in evidence
  - deletes smoke rows after the run
- `scripts/quality/run_quality_gate.sh` records default skipped evidence.
- `scripts/smoke/run_postgres_test_smoke_suite.py` includes the detail smoke as
  a suite stage after the document library smoke.

## Manual PostgreSQL Smoke

Use the test database only:

```bash
NEX_CX_TEST_DATABASE_URL=<test database URL> \
NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE=1 \
NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_cx_document_detail_postgres_smoke.py --summary
```

Expected summary:

```text
cx_document_detail_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
```

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py -q
```

Protected PostgreSQL smoke:

```bash
NEX_CX_TEST_DATABASE_URL=<redacted test DB URL> \
NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE=1 \
NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_cx_document_detail_postgres_smoke.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
167 passed, 1 warning
```

Observed protected PostgreSQL smoke:

```text
cx_document_detail_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
migration planned=12 applied=0 skipped=12
wrong_owner_status=404
owner_active_content_count=1
detail_projection_schema_version=cx_document_detail_projection.v1
detail_source_kind=postgres-read
cleanup content_rows_after_delete=0 source_rows_after_delete=0
```

Observed full quality gate:

```text
1597 passed, 1 warning
statement_coverage=97.93%
branch_coverage=93.62%
contract_validation=pass schemas=45 examples=74 negative_examples=50 openapi=7
cx_document_detail_postgres_smoke=skipped reason=NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
