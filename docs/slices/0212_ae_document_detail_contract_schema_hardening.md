# Slice 0212: AE Document Detail Contract/Schema Hardening

## Scope

Slice 0212 fixes the public contract for the AE document detail facade added in
Slice 0211.

Implemented:

- Added `contracts/schemas/service/nex_ae_api/document_detail_projection.v1.schema.json`.
- Added a valid `ae_document_detail_projection.v1` contract fixture.
- Added a negative fixture that rejects raw summary and local storage path
  leakage.
- Registered the new positive and negative fixtures with contract validation.
- Added `GET /api/v1/documents/{document_id}` to the AE OpenAPI document with a
  closed response schema.
- Added runtime projection schema validation coverage in
  `tests/test_nex_ae_documents.py`.
- Added OpenAPI hardening assertions in `tests/test_contract_validation.py`.

## Boundary

The AE detail contract is intentionally not a pass-through copy of the CX detail
projection. It preserves user/workspace display metadata, status, summary
preview/hash metadata, processing status, safe lineage hashes, and links while
requiring redaction flags for source bytes, markdown text, raw summary text,
embedding vectors, storage keys, storage URIs, and local filesystem paths.

## Evidence

Targeted regression and contract validation:

```bash
./.venv/bin/pytest tests/test_nex_ae_documents.py tests/test_contract_validation.py -q
./.venv/bin/python scripts/quality/validate_contracts.py contracts
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
44 passed, 1 warning
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```

Observed full quality gate:

```text
1616 passed, 1 warning
statement_coverage=97.95%
branch_coverage=93.68%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
cx_document_detail_postgres_smoke=skipped reason=NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
