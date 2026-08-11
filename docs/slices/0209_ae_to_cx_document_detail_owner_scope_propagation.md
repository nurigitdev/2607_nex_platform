# Slice 0209: AE to CX Document Detail Owner-Scope Propagation

## Scope

Slice 0209 closes the AE to CX owner-scope hop for document library reads.
Slice 0207 made CX document detail owner-scoped, so AE must forward the stable
owner context captured during upload instead of calling document detail by
document ID alone.

Implemented:

- `CxDocumentLibraryClient.get_document` now requires `tenant_id` and
  `owner_user_id`.
- `HttpCxDocumentLibraryClient.get_document` passes those values as query
  parameters to `GET /api/v1/documents/{document_id}`.
- `owner_scope_query_params` normalizes and validates owner-scope values before
  any CX call.
- `build_document_library_item_from_cx` centralizes the list/search composition
  path so both routes use the same owner-scoped CX detail call.
- Invalid stored owner scope maps to `ae.document_owner_scope_invalid` with HTTP
  422 and no outbound CX request.

## Boundary

AE still does not persist raw source bytes, markdown content, local storage
paths, or raw summary text. The owner scope is treated as routing and
authorization context for CX reads; CX remains responsible for enforcing
owner-scoped document access.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_documents.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
16 passed, 1 warning
```

Observed full quality gate:

```text
1603 passed, 1 warning
statement_coverage=97.95%
branch_coverage=93.67%
contract_validation=pass schemas=45 examples=74 negative_examples=50 openapi=7
cx_document_detail_postgres_smoke=skipped reason=NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
