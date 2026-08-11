# Slice 0223: AE Web Fetch-Mode Static Regression Harness

## Scope

Slice 0223 adds a static regression harness that exercises AE Web fetch-mode
client composition without making live network calls.

Implemented:

- Added `apps/nex-ae-web/src/fetchModeHarness.js`.
- Added `runFetchModeHarness()` to run document detail, upload, and retrieval
  fetch clients through an injected fake fetch implementation.
- Required injected fetch so static regression cannot accidentally call a live
  AE API.
- Added safe harness result summaries under `ae_web_fetch_mode_harness.v1`.
- Added Node built-in tests for all three AE facade routes, request metadata,
  normalized results, no raw prompt/source rendering, missing fetch guard, and
  missing document guard.
- Updated static Python regression guards for harness wiring, package metadata,
  and redaction-sensitive strings.

## Boundary

This is not a live API smoke. It is a fetch-mode compatibility harness:

```text
safe runtime config fetch mode
  -> createAeWebClients({ mode: "fetch", fetchImpl })
  -> document detail fetch client
  -> upload fetch client
  -> retrieval fetch client
  -> fake AE facade responses
```

The harness may assert route URLs, request methods, selected document IDs,
upload metadata, retrieval metadata, result statuses, package IDs, and evidence
counts.

It must not call the network, include browser credentials beyond same-origin
request semantics, render raw prompts, include raw source text, include source
preview/chunk text, expose provider endpoints, expose database endpoints, expose
storage locations, or reference local filesystem paths.

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
node --check apps/nex-ae-web/src/fetchModeHarness.js
node --check apps/nex-ae-web/src/runtimeConfig.js
node --check apps/nex-ae-web/src/clientRegistry.js
node --check apps/nex-ae-web/src/documentDetailClient.js
node --check apps/nex-ae-web/src/uploadSurface.js
node --check apps/nex-ae-web/src/uploadClient.js
node --check apps/nex-ae-web/src/documentScope.js
node --check apps/nex-ae-web/src/retrievalClient.js
```

Static dev-server smoke:

```bash
PORT=5223 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5223/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py: 8 passed
npm --prefix apps/nex-ae-web test: 32 tests passed across 8 suites
JavaScript syntax check: pass
dev-server smoke: http_status=200 with Slice 0223 and fetch-mode config anchors
```

Observed full quality gate:

```text
1629 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```
