# Slice 1085: AE Web Generation Runtime Composition

## Goal

Compose the grounded-generation client into the existing authenticated AE Web
runtime without creating a parallel authentication or configuration path.

## Implementation

- Registered mock and fetch grounded-generation clients beside the existing
  document, upload, retrieval, feedback, repair, and artifact adapters.
- Reused the normalized same-origin AE base URL and injected fetch
  implementation from the authenticated runtime.
- Exposed grounded-generation client mode in registry and runtime diagnostics
  without exposing service tokens, provider URLs, or database endpoints.
- Added optional mock response factories so later lifecycle wiring can model
  queued, running, completed, failed, cancelled, and recovery paths
  deterministically.

## Verification

```bash
node --test apps/nex-ae-web/test/clientRegistry.test.mjs \
  apps/nex-ae-web/test/authenticatedRuntime.test.mjs \
  apps/nex-ae-web/test/runtimeDiagnostics.test.mjs
npm test --prefix apps/nex-ae-web
scripts/quality/run_slice_gate.sh --service nex-ae-web \
  --test tests/test_ae_web_grounded_generation_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py \
  --smoke scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py
```

## Observed Evidence

- Focused runtime composition tests: `10 passed`.
- AE Web Node regression: `254 passed`.
- Slice Gate: `273 passed`; focused audit statement and branch coverage both
  `100.00%`.
- Contract Gate: `108` schemas, `166` positive examples, `129` negative
  examples, and `7` OpenAPI documents passed.
- Boundary progress: gaps `8`, open `5`, issues `0`, next `1086`.
