# Slice 0216: AE Web Document Detail Client Adapter Foundation

## Scope

Slice 0216 separates the AE Web document detail surface from direct mock state
lookup by adding a browser-side client adapter boundary.

Implemented:

- Added `apps/nex-ae-web/src/documentDetailClient.js`.
- Added a mock document detail client used by the current static shell.
- Added a fetch document detail client that targets the AE facade route
  `/api/v1/documents/{document_id}`.
- Kept live browser calls deferred: the fetch adapter uses same-origin
  credentials and does not embed service tokens, API keys, provider URLs, or
  database details.
- Updated `main.js` so document detail rendering is asynchronous and handles
  loading, stale response, and typed error states.
- Added Node built-in tests for mock success, not-found, fetch success, HTTP
  failure, network failure, and invalid projection branches.
- Updated static Python regression guards for adapter files, DOM anchors,
  responsive state, package metadata, and redaction-sensitive strings.

## Boundary

The default runtime mode remains mock-first. The browser shell must not call CX
document detail directly and must not hold service-to-service credentials.

Future live integration should attach at the adapter boundary:

```text
nex-ae-web documentDetailClient.fetch
  -> nex-ae-api GET /api/v1/documents/{document_id}
  -> nex-cx owner-scoped document detail
```

The adapter normalizes AE-safe surface fields only: route, projection schema,
owner scope, source service/kind, processing/extraction/summary statuses,
confidence bucket, score, and adapter mode. Raw source, markdown text, raw
summary, embedding vectors, storage keys, storage URIs, local filesystem paths,
provider endpoints, and secrets remain outside the web surface.

## Evidence

Targeted Python static regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
```

Targeted Node adapter regression:

```bash
npm --prefix apps/nex-ae-web test
```

JavaScript syntax check:

```bash
node --check apps/nex-ae-web/src/main.js
node --check apps/nex-ae-web/src/documentDetailClient.js
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
Python static regression: 5 passed
Node adapter regression: 5 tests passed
JavaScript syntax check: pass
dev-server HTTP smoke: http_status=200 with Slice 0216 and document-detail-panel
```

Observed full quality gate:

```text
1626 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
ae_document_detail_postgres_smoke=skipped reason=NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
