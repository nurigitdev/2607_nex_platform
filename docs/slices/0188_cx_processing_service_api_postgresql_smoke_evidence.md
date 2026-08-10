# Slice 0188: CX Processing Service API PostgreSQL Smoke Evidence

## Scope

Slice 0188 adds guarded PostgreSQL smoke evidence for the CX document processing
service API read path wired in Slice 0187.

Implemented:

- `scripts/smoke/run_cx_processing_postgres_api_smoke.py`
- opt-in `NEX_CX_PROCESSING_POSTGRES_API_SMOKE=1` test-profile guard
- migration refresh before smoke execution
- FastAPI `GET /api/v1/documents/{document_id}/processing` persisted projection
  check against a SQLAlchemy-backed CX content repository
- memory fallback bypass check so persisted rows remain the preferred source
- integration into the default quality gate as a skipped protected smoke
- integration into `run_postgres_test_smoke_suite.py`
- processing persistence decision status update to
  `service_api_postgres_smoke_ready_ag_pending`

## Decision

The smoke seeds a source document and a failed processing run into the CX test
database, then calls the service API through `TestClient`. It verifies the API
returns the persisted read-model projection rather than the in-memory runtime
record, and that raw source text and raw error details are absent from the
response.

The smoke remains opt-in and restricted to the `test` profile because it writes
and deletes rows in `nex_cx_test`. Normal regression and CI keep the script in
skipped mode unless the protected environment variable is explicitly enabled.

## Next Slice

Recommended next slice:

- `0189_cx_processing_run_operations_projection_contract`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_nex_cx_processing.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
pass
```

Observed targeted result:

```text
171 passed
```

Protected PostgreSQL smoke:

```bash
NEX_CX_TEST_DATABASE_URL=postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test \
NEX_CX_PROCESSING_POSTGRES_API_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_cx_processing_postgres_api_smoke.py --summary
```

Observed protected smoke result:

```text
cx_processing_postgres_api_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1432 passed
statement_coverage=98.06%
branch_coverage=93.65%
contract_validation=pass
```
