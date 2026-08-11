# Slice 0211: AE Document Detail Facade API Wiring

## Scope

Slice 0211 adds the AE-facing document detail read path that builds on the
owner-scoped CX detail projection hardened in Slice 0210.

Implemented:

- Added `GET /api/v1/documents/{document_id}` to `nex-ae-api`.
- Added upload-handoff lookup by CX `document_id` so AE can resolve detail
  requests from its safe handoff state before calling CX.
- Added `build_document_detail_from_cx` and
  `build_document_detail_projection`.
- The facade calls the CX document detail endpoint exactly once using the
  upload handoff owner scope (`tenant_id`, `owner_user_id`).
- Missing AE handoff records return `ae.document_not_found` without calling CX.
- Invalid stored owner scope returns `ae.document_owner_scope_invalid` without
  calling CX.
- CX failures are mapped through the existing AE problem response path.

## Boundary

AE returns an AE-safe detail projection and does not pass through the complete
CX detail payload. Source bytes, markdown text, raw summaries, embedding
vectors, storage keys, storage URIs, and local filesystem paths remain outside
the AE response.

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
25 passed, 1 warning
```

Observed full quality gate:

```text
1614 passed, 1 warning
statement_coverage=97.95%
branch_coverage=93.68%
contract_validation=pass schemas=46 examples=75 negative_examples=51 openapi=7
cx_document_detail_postgres_smoke=skipped reason=NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
