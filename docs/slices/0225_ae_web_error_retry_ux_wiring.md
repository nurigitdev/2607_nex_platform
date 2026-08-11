# Slice 0225: AE Web Error/Retry UX Wiring

## Scope

Slice 0225 wires safe error and retry feedback into the AE Web operation
surfaces created in Slice 0224.

Implemented:

- Added `apps/nex-ae-web/src/operationFeedback.js`.
- Added `ae_web_operation_feedback.v1` safe feedback summaries.
- Added retry controls for document detail, upload, and retrieval operations.
- Retry buttons are shown only when the operation is failed and retryable.
- Added panel feedback areas for document detail, upload, and retrieval.
- Added Node built-in tests for pending, running, success, retryable failure,
  non-retryable failure, invalid retry summaries, and retry reason fallback.
- Updated static Python regression guards for feedback/retry wiring, responsive
  styles, package metadata, and redaction-sensitive strings.

## Boundary

This Slice does not add live API authentication, service credentials, or a new
backend route. It only improves browser-side operational feedback for existing
client adapters.

Feedback may show phase, status, retry availability, retry reason code, and a
short localized user message.

Feedback must not render raw exception messages, raw prompts, raw source text,
source preview/chunk text, service tokens, provider endpoints, database
endpoints, storage locations, or local filesystem paths.

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
PORT=5225 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5225/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py: 8 passed
npm --prefix apps/nex-ae-web test: 39 tests passed across 10 suites
JavaScript syntax check: pass
dev-server smoke: http_status=200 with Slice 0225 and retry/feedback anchors
```

Observed full quality gate:

```text
1629 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```
