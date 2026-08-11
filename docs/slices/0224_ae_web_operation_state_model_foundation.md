# Slice 0224: AE Web Operation State Model Foundation

## Scope

Slice 0224 adds a shared AE Web operation state model for document detail,
upload, and retrieval client work.

Implemented:

- Added `apps/nex-ae-web/src/operationState.js`.
- Added `ae_web_operation_state.v1` safe operation summaries.
- Normalized browser operation phases to `idle`, `running`, `succeeded`, and
  `failed`.
- Wired document detail, upload, and retrieval flows through the common state
  model.
- Added operation attempt, retryability, route, client mode, result status, and
  error status to safe previews.
- Added Node built-in tests for successful transitions, retryable failures,
  invalid operation IDs, unsupported phases, invalid attempts, invalid summary
  input, and metadata filtering.
- Updated static Python regression guards for operation state wiring, package
  metadata, and redaction-sensitive strings.

## Boundary

This Slice does not add a new backend route or live browser API call. It creates
the browser-side state foundation required before richer error/retry UX and
runtime diagnostics are added.

Operation summaries may show phase, status, attempt count, retryability, client
mode, route, result status, and error status.

They must not expose browser service tokens, raw prompts, raw source content,
source previews, provider endpoints, database endpoints, storage locations, or
local filesystem paths.

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
PORT=5224 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5224/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py: 8 passed
npm --prefix apps/nex-ae-web test: 36 tests passed across 9 suites
JavaScript syntax check: pass
dev-server smoke: http_status=200 with Slice 0224 and fetch-mode config anchors
```

Observed full quality gate:

```text
1629 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```
