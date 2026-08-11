# Slice 0215: AE Web Document Surface Audit and Refactoring Checkpoint

## Scope

Slice 0215 audits the static `nex-ae-web` document surface after Slices
0211-0214 established and proved the AE document detail facade.

Implemented:

- Added a safe document detail panel to the AE Web shell.
- Refactored document mock state around a selected document surface with
  `ae_document_detail_projection.v1` metadata.
- Added `documentDetailRoute`, `buildDocumentSurface`, and
  `renderDocumentDetail` as the browser-side boundary where a future
  service-authenticated AE API mediation path can attach.
- Updated static regression tests for DOM anchors, projection fields, route
  alignment, responsive styles, package metadata, and raw payload guardrails.
- Updated `apps/nex-ae-web` metadata and README to Slice 0215.

## Audit Decision

The browser shell remains static and mock-first. It should not call CX document
detail directly. The future live path stays:

```text
nex-ae-web -> nex-ae-api GET /api/v1/documents/{document_id}
           -> nex-cx GET /api/v1/documents/{document_id}?tenant_id=...&owner_user_id=...
```

`nex-ae-web` may display AE-safe detail projection fields: route, projection
schema, owner scope, source service/kind, extraction status, summary status,
confidence bucket, and retrieval score. It must not display or store source
bytes, markdown text, raw summaries, embedding vectors, storage keys, storage
URIs, or local filesystem paths.

## Refactoring Checkpoint

The document list and document detail panel are now separate render surfaces.
That keeps the current mock shell small while preventing the detail surface from
depending on CX-internal payload structure.

No browser-authenticated AE API client was added in this slice. That remains
deferred until the web mediation/auth boundary is defined.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
```

Static dev-server smoke:

```bash
PORT=5215 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5215/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
5 passed
dev-server HTTP smoke returned 200 and included document-detail-panel.
```

Observed full quality gate:

```text
1626 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
ae_document_detail_postgres_smoke=skipped reason=NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
