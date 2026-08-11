# Slice 0214: AE Document Detail PostgreSQL Smoke Evidence

## Scope

Slice 0214 adds protected PostgreSQL smoke evidence for the AE document detail
facade created in Slices 0211-0213.

Implemented:

- Added `scripts/smoke/run_ae_document_detail_postgres_smoke.py`.
- The smoke is protected by `NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE=1` and
  requires the `test` profile.
- The smoke uses the real CX SQLAlchemy repository against
  `NEX_CX_TEST_DATABASE_URL`.
- The smoke exercises this in-process service path:

```text
AE POST /api/v1/uploads
  -> CX POST /api/v1/documents/uploads
  -> PostgreSQL write
AE GET /api/v1/documents/{document_id}
  -> CX GET /api/v1/documents/{document_id}?tenant_id=...&owner_user_id=...
  -> PostgreSQL read
```

- Added default-skip wiring to `scripts/quality/run_quality_gate.sh`.
- Added the AE detail stage to `scripts/smoke/run_postgres_test_smoke_suite.py`.
- Added SQLite regression coverage for execution, cleanup, failure paths, CLI
  output, and redaction-safe evidence.

## Boundary

The smoke proves the AE facade forwards owner scope to CX and reads from the CX
test database, but it still keeps AE free of raw content persistence. Evidence
must not include source text, local source paths, storage keys, storage URIs,
raw summaries, or embedding vectors.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py -q
```

Protected AE PostgreSQL smoke:

```bash
NEX_CX_TEST_DATABASE_URL=... \
NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE=1 \
NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_ae_document_detail_postgres_smoke.py --summary
```

Protected PostgreSQL suite:

```bash
NEX_POSTGRES_TEST_SMOKE_SUITE=1 \
NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_postgres_test_smoke_suite.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
175 passed, 1 warning
```

Observed protected smoke result:

```text
ae_document_detail_postgres_smoke=pass service=nex-ae-api cx_db_env=NEX_CX_TEST_DATABASE_URL
postgres_test_smoke_suite=pass services=5 profile=test primary=nex-cx stages=23
```

Observed full quality gate:

```text
1625 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
ae_document_detail_postgres_smoke=skipped reason=NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
