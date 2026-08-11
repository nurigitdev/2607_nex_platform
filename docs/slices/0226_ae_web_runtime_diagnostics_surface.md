# Slice 0226: AE Web Runtime Diagnostics Surface

## Scope

Slice 0226 adds a browser-safe runtime diagnostics surface for AE Web.

Implemented:

- Added `apps/nex-ae-web/src/runtimeDiagnostics.js`.
- Added `ae_web_runtime_diagnostics.v1` summaries.
- Summarized runtime config, client registry, and operation state in one
  diagnostics object.
- Added a runtime diagnostics panel to the AE Web shell.
- Exposed safe client mode, AE base path, fetch flag, operation count, failed
  operation count, and retryable operation count.
- Added Node built-in tests for mock runtime diagnostics, fetch-mode
  diagnostics without live network calls, invalid diagnostics, and invalid
  operation collections.
- Updated static Python regression guards for diagnostics DOM anchors, module
  wiring, package metadata, and redaction-sensitive strings.

## Boundary

This Slice does not introduce live browser API authentication or any provider,
database, or storage endpoint exposure. The diagnostics panel is intentionally
browser-safe and describes only the AE Web runtime composition.

Diagnostics may show client mode, browser-safe AE facade base path, feature
flags, client registry shape, operation phases, operation status codes, retry
counts, and redaction metadata.

Diagnostics must not expose service tokens, API keys, raw prompts, raw source
content, source previews, provider endpoints, database endpoints, storage
locations, or local filesystem paths.

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
node --check apps/nex-ae-web/src/runtimeDiagnostics.js
node --check apps/nex-ae-web/src/operationFeedback.js
node --check apps/nex-ae-web/src/operationState.js
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
PORT=5226 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5226/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py: 8 passed
npm --prefix apps/nex-ae-web test: 42 tests passed across 11 suites
JavaScript syntax check: pass
dev-server smoke: http_status=200 with Slice 0226 and runtime diagnostics anchors
```

Observed full quality gate:

```text
1629 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```
