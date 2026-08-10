# Slice 0190: AG CX Processing Operations Projection PostgreSQL Smoke

## Scope

Slice 0190 wires the CX processing run operations projection contract from
Slice 0189 into AG read-only APIs and adds guarded PostgreSQL smoke evidence.

Implemented:

- `nex_ag.processing_operations`
- `GET /admin/v1/operations/cx-processing-runs`
- `GET /admin/v1/operations/cx-processing-runs/{pipeline_run_id}`
- SQLAlchemy-backed read-only AG store over `cx_document_processing_runs` and
  `cx_document_processing_steps`
- OpenAPI route documentation for the new AG operations APIs
- `scripts/smoke/run_ag_cx_processing_run_postgres_smoke.py`
- default quality-gate skipped-mode smoke integration
- optional PostgreSQL test smoke suite stage
  `ag_cx_processing_run_postgres`
- processing persistence decision status update to
  `ag_operations_postgres_smoke_ready`

## Decision

AG reads CX processing run rows directly only through a read-only operations
source. The projection is scoped to `nex-cx` and exposes list/detail operator
views without writing to the CX database.

The list endpoint defaults to `include_steps=false` for dashboard/table use.
The detail endpoint always includes safe step metadata. Raw source text,
markdown, chunk text, summary text, vectors, prompts, raw step output, private
payloads, and raw error details remain excluded. Failed step debugging uses
`error_code`, `error_detail_sha256`, and `error_retryable`.

## Next Slice

Potential next slice:

- `0191_cx_processing_operations_dashboard_integration`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_processing_operations.py tests/test_smoke_helpers.py tests/test_contract_validation.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py -q
```

Observed targeted result:

```text
174 passed
```

OpenAPI/contract regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q
./.venv/bin/python scripts/quality/validate_contracts.py
```

Observed result:

```text
16 passed
contract_validation=pass schemas=42 examples=71 negative_examples=49 openapi=7
```

Default skipped smoke:

```bash
./.venv/bin/python scripts/smoke/run_ag_cx_processing_run_postgres_smoke.py --summary
./.venv/bin/python scripts/smoke/run_postgres_test_smoke_suite.py --summary
```

Observed skipped result:

```text
ag_cx_processing_run_postgres_smoke=skipped reason=NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE
postgres_test_smoke_suite=skipped reason=NEX_POSTGRES_TEST_SMOKE_SUITE
```

Protected PostgreSQL smoke:

```bash
NEX_CX_TEST_DATABASE_URL=postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test \
NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_ag_cx_processing_run_postgres_smoke.py --summary
```

Observed protected smoke result:

```text
ag_cx_processing_run_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL list=1 detail_steps=2 error_hashes=1
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed full quality result:

```text
1453 passed
statement_coverage=98.03% threshold=95.00%
branch_coverage=93.51% threshold=85.00%
contract_validation=pass schemas=42 examples=71 negative_examples=49 openapi=7
```
