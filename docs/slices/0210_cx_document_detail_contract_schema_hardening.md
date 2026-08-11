# Slice 0210: CX Document Detail Contract/Schema Hardening

## Scope

Slice 0210 hardens `GET /api/v1/documents/{document_id}` after AE began
propagating owner scope in Slice 0209.

Implemented:

- Added `contracts/schemas/service/nex_cx/document_detail_projection.v1.schema.json`.
- Added a valid `cx_document_detail_projection.v1` contract fixture.
- Added a negative fixture that rejects source storage path leakage.
- Registered the new positive and negative fixtures with contract validation.
- Tightened the CX OpenAPI detail endpoint:
  - `tenant_id` and `owner_user_id` are marked required.
  - the response root and document object are no longer open-ended.
  - source lineage, upload metadata, extraction metadata, and privacy flags are
    explicitly represented.
- Updated runtime detail filters so missing owner scope is rejected as
  `cx.document_detail_query_invalid`.
- Projected legacy repository rows without embedded `ownership_ref` back to
  canonical OA refs from indexed legacy owner columns.

## Boundary

The detail projection remains metadata-only. It must not include source bytes,
markdown content, summary body, embedding vectors, storage keys, storage URIs,
or local storage paths.

## Evidence

Targeted regression and contract validation:

```bash
./.venv/bin/pytest tests/test_nex_cx_document_library.py tests/test_nex_cx_ingestion.py tests/test_contract_validation.py -q
./.venv/bin/python scripts/quality/validate_contracts.py contracts
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
134 passed, 1 warning
contract_validation=pass schemas=46 examples=75 negative_examples=51 openapi=7
```

Observed full quality gate:

```text
1605 passed, 1 warning
statement_coverage=97.95%
branch_coverage=93.67%
contract_validation=pass schemas=46 examples=75 negative_examples=51 openapi=7
cx_document_detail_postgres_smoke=skipped reason=NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
