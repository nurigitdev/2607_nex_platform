# Slice 0206: CX Document Detail Boundary Audit and Projection Foundation

## Scope

Slice 0206 defines a raw-safe, owner-scoped CX document detail projection before
rewiring the existing document detail API.

Implemented:

- `build_document_detail_query_filters`
  - normalizes `document_id`, `tenant_id`, and `owner_user_id`
  - records canonical `cx.document`, `oa.tenant`, and `oa.user` refs
  - requires `lifecycle_status=ACTIVE`
- `build_document_detail_projection`
  - returns `None` for missing, inactive, or wrong-owner documents
  - collapses not-found and not-authorized outcomes for caller privacy
  - includes service source metadata, query filters, safe document metadata, and
    boundary audit metadata
- `project_document_detail_item`
  - reuses the Slice 0201 document library item metadata
  - adds safe source lineage without `storage_uri`, `storage_key`, or local
    `source_storage_path`
  - adds upload metadata without source content
- `build_document_detail_boundary_audit`
  - records the legacy route risk for `GET /api/v1/documents/{document_id}`
  - marks the replacement projection as owner-scoped and raw-safe

## Boundary Audit

Current legacy route:

```text
GET /api/v1/documents/{document_id}
```

Current payload shape:

```text
cx_upload_registration.v1
```

Boundary issue:

```text
owner_scope_required=false
may_expose_local_storage_path=true
```

New projection:

```text
cx_document_detail_projection.v1
```

New projection guarantees:

```text
owner_scope_required=true
not_found_and_not_authorized_collapsed=true
raw_source_included=false
raw_summary_included=false
embedding_vector_included=false
local_storage_path_included=false
storage_uri_included=false
storage_key_included=false
```

## Next Slice

Recommended next slice:

- `0207_cx_document_detail_service_api_wiring`

That slice should wire the existing detail route to this projection and map
`None` to a raw-safe 404.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_document_library.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
17 passed, 1 warning
```

Observed full quality gate:

```text
1587 passed, 1 warning
statement_coverage=97.91%
branch_coverage=93.58%
contract_validation=pass schemas=45 examples=74 negative_examples=50 openapi=7
```
