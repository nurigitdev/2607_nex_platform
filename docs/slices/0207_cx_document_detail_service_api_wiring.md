# Slice 0207: CX Document Detail Service API Wiring

## Scope

Slice 0207 wires the Slice 0206 raw-safe document detail projection into the
existing CX service API route:

```text
GET /api/v1/documents/{document_id}
```

Implemented:

- replaces the legacy `cx_upload_registration.v1` read response with
  `cx_document_detail_projection.v1`
- keeps service-claim authentication on the existing route
- adds `tenant_id` and `owner_user_id` query filters for owner-scoped detail
  reads
- collapses missing, inactive, and wrong-owner documents to the same
  `cx.document_not_found` response
- maps invalid detail query parameters to `cx.document_detail_query_invalid`
- maps repository failures to retryable problem responses
- preserves safe extraction status metadata for AE compatibility without
  exposing source content or local storage paths
- updates `nex-cx.openapi.yaml` to describe the detail projection response

## Boundary

The route remains a CX service API endpoint, but callers should treat the
response as a projection, not as the upload registration storage record.

Raw data remains excluded:

```text
raw_source_included=false
raw_summary_included=false
embedding_vector_included=false
storage_path_redacted=true
```

## Next Slice

Recommended next slice:

- `0208_cx_document_detail_postgresql_smoke_evidence`

That slice should run the detail endpoint against `nex_cx_test` with a real
PostgreSQL-backed content repository.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_document_library.py tests/test_nex_cx_ingestion.py tests/test_nex_ae_documents.py tests/test_contract_validation.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
142 passed, 1 warning
```

Observed full quality gate:

```text
1590 passed, 1 warning
statement_coverage=97.91%
branch_coverage=93.60%
contract_validation=pass schemas=45 examples=74 negative_examples=50 openapi=7
```
