# Slice 0227: AE Web Static Browser Smoke Evidence Runner

## Scope

Slice 0227 adds a repeatable static browser smoke evidence runner for AE Web.

Implemented:

- Added `scripts/smoke/run_ae_web_static_browser_smoke.py`.
- The runner starts the AE Web dev server, fetches the served browser shell,
  validates required DOM anchors, stops the dev server, and emits a compact
  smoke summary.
- Added the runner to `scripts/quality/run_quality_gate.sh` after contract
  validation.
- Added Python regression tests for pass, missing-anchor failure, retry after
  temporary HTTP unavailability, timeout failure, graceful process shutdown,
  stuck process kill, and summary output.
- Updated static Python regression guards for runner wiring, package metadata,
  and redaction-sensitive strings.

## Boundary

This is a static browser smoke, not a live AE API, PostgreSQL, CX, MO, or DGX
smoke. It verifies that the browser shell is served over HTTP and that the
runtime config, diagnostics, feedback, retry, and retrieval anchors are present.

The runner must not require service tokens, API keys, provider endpoints,
database endpoints, storage locations, raw source content, or live provider
connectivity.

## Evidence

Targeted Python static regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py tests/test_ae_web_static_browser_smoke.py -q
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

Static browser smoke:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_static_browser_smoke.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py + tests/test_ae_web_static_browser_smoke.py: 17 passed
npm --prefix apps/nex-ae-web test: 42 tests passed across 11 suites
JavaScript syntax check: pass
Python smoke runner syntax check: pass
ae_web_static_browser_smoke=pass slice=Slice_0227 anchors=11 url=http://127.0.0.1:5227/
```

Observed full quality gate:

```text
1638 passed, 1 warning
statement_coverage=97.99% threshold=95.00%
branch_coverage=93.75% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
ae_web_static_browser_smoke=pass slice=Slice_0227 anchors=11 url=http://127.0.0.1:5227/
```
