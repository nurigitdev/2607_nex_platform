# Slice 0201: CX Owner-Scoped Document Library Projection

## Scope

Slice 0201 adds the CX-side read-model foundation for listing active documents
within one OA-backed owner scope.

Implemented:

- `nex_cx.document_library` builds a raw-safe document library projection from
  persisted CX content metadata.
- CX repository ports now expose owner-scoped ACTIVE content listing.
- In-memory and SQLAlchemy repository adapters use the canonical
  `tenant_ref + owner_subject_ref` columns for list filtering.
- latest persisted document summary and summary embedding metadata can be read
  without loading raw summary text or embedding vectors.
- `document_library_projection.v1` contract, success example, and storage URI
  leak negative fixture are registered in contract validation.

## Projection Boundary

The projection exposes stable metadata only:

- owner subject refs and upload/content IDs
- source hash, size, MIME type, lifecycle status, retrieval policy metadata
- summary hash/preview/count and summary embedding hash/dimension
- latest processing run status/step counts

It does not expose raw source bytes, extracted Markdown text, summary body,
embedding vectors, local filesystem paths, provider secrets, or database
passwords.

## Repository Query Semantics

Owner list queries are bounded to 1-100 rows and sorted by:

```text
created_at DESC, content_object_id DESC
```

The query intentionally uses canonical owner columns:

```text
tenant_ref_type/id
owner_subject_ref_type/id
lifecycle_status = ACTIVE
```

The legacy `tenant_id` and `owner_user_id` aliases remain compatibility fields,
but they are no longer the preferred indexing surface for document library
queries.

## Next Slice

Recommended next slice:

- `0202_cx_document_library_service_api_wiring`

That slice should wire a CX route around this projection and update OpenAPI.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_document_library.py tests/test_nex_cx_repository.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
131 passed
```

Observed full quality gate:

```text
1563 passed
statement_coverage=97.86%
branch_coverage=93.50%
contract_validation=pass schemas=45 examples=74 negative_examples=50 openapi=7
```
