# Slice 0219: AE Web Upload Client Adapter Foundation

## Scope

Slice 0219 separates the AE Web upload surface from direct mock state by adding
a client adapter boundary.

Implemented:

- Added `apps/nex-ae-web/src/uploadClient.js`.
- Added mock and fetch upload client adapters.
- Added normalized upload submission results under
  `ae_web_upload_client.v1`.
- Updated the upload panel with a submit action and safe client result summary.
- Kept upload draft construction in `uploadSurface.js` so ownership and handoff
  payload shape remain centralized.
- Added Node built-in tests for mock success, duplicate/already-exists outcome,
  fetch POST request shape, HTTP failure, network failure, missing fetch, and
  invalid handoff branches.
- Updated static Python regression guards for DOM anchors, client adapter
  strings, package metadata, responsive styles, and redaction-sensitive strings.

## Boundary

The browser still does not upload raw file bytes in this Slice. It submits the
safe metadata/handoff draft only:

```text
AE Web upload draft
  -> upload client adapter
  -> nex-ae-api POST /api/v1/uploads
  -> future AE-to-CX upload handoff
```

The upload preview may show filenames, content type, size, source hash,
owner-scope refs, handoff IDs, document IDs, dedupe status, route metadata, and
client mode.

It must not show raw source content, base64 content, service tokens, provider
URLs, CX storage locations, or database details.

## Evidence

Targeted Python static regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
```

Targeted Node Web regression:

```bash
npm --prefix apps/nex-ae-web test
```

JavaScript syntax check:

```bash
node --check apps/nex-ae-web/src/main.js
node --check apps/nex-ae-web/src/documentDetailClient.js
node --check apps/nex-ae-web/src/uploadSurface.js
node --check apps/nex-ae-web/src/uploadClient.js
node --check apps/nex-ae-web/src/documentScope.js
```

Static dev-server smoke:

```bash
PORT=5219 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5219/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py: 7 passed
npm --prefix apps/nex-ae-web test: 17 tests passed across 4 suites
JavaScript syntax check: pass
dev-server smoke: http_status=200 with Slice 0219 and upload-client-summary
```

Observed full quality gate:

```text
1628 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```
