# Slice 0220: AE Web Retrieval Context Client Adapter Foundation

## Scope

Slice 0220 separates the AE Web retrieval scope surface from direct mock state
by adding a retrieval client adapter boundary.

Implemented:

- Added `apps/nex-ae-web/src/retrievalClient.js`.
- Added mock and fetch retrieval context client adapters.
- Added normalized retrieval client results under
  `ae_web_retrieval_client.v1`.
- Updated chat submit handling so retrieval requests pass through the mock
  retrieval client before rendering assistant state.
- Added a retrieval client summary and safe retrieval result preview.
- Added Node built-in tests for grounded mock success, general chat skip,
  no-answer records, fetch POST request shape, HTTP failure, network failure,
  unavailable fetch, and invalid record branches.
- Updated static Python regression guards for DOM anchors, client adapter
  strings, package metadata, responsive styles, and redaction-sensitive strings.

## Boundary

The workflow remains browser mock-first. The browser may carry a user message in
the outbound AE API request because the AE facade requires it, but the rendered
preview and normalized client result only expose safe operational metadata:

```text
AE Web document scope + prompt
  -> retrieval client adapter
  -> nex-ae-api POST /api/v1/retrieval/contexts
  -> future nex-cx retrieval package
```

The retrieval preview may show route metadata, selected document IDs, execution
mode, retrieval profile, `top_k`, source-preview disabled state, interaction ID,
package ID, evidence count, confidence, no-answer reason, and retryability.

It must not show raw prompt fields, raw source text, chunk text, source preview
text, service tokens, provider URLs, storage paths, or database details.

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
node --check apps/nex-ae-web/src/retrievalClient.js
```

Static dev-server smoke:

```bash
PORT=5220 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5220/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py: 7 passed
npm --prefix apps/nex-ae-web test: 22 tests passed across 5 suites
JavaScript syntax check: pass
dev-server smoke: http_status=200 with Slice 0220 and retrieval-client-summary
```

Observed full quality gate:

```text
1628 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```
