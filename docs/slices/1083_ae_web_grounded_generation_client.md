# Slice 1083: AE Web Grounded Generation Client

## Goal

Add one same-origin browser adapter for AE grounded-generation admission,
lifecycle control, verified response, and citation-quality routes.

## Implementation

- Added mock and fetch clients for interaction admission/read, progress,
  refresh, cancellation, retry, recovery, generated response, and citation
  quality.
- Every fetch uses same-origin cookies and canonical AE routes. The browser
  adapter never adds a service token or calls CX/MO directly.
- Each response is checked against its AE schema-version discriminator before
  it reaches UI state.
- Lifecycle projections remain metadata-only. Owner-visible generated content
  is accepted only from the generated-response or completed refresh contract.
- Network and HTTP failures are normalized into bounded retry metadata without
  retaining transport exception details.

## Verification

```bash
node --test apps/nex-ae-web/test/groundedGenerationClient.test.mjs
npm test --prefix apps/nex-ae-web
scripts/quality/run_slice_gate.sh --service nex-ae-web \
  --test tests/test_ae_web_grounded_generation_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py \
  --smoke scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py
```

## Observed Evidence

- Focused client tests: `7 passed`.
- AE Web Node regression: `246 passed`.
- Slice Gate: `273 passed`; focused audit statement and branch coverage both
  `100.00%`.
- Contract Gate: `108` schemas, `166` positive examples, `129` negative
  examples, and `7` OpenAPI documents passed.
- Boundary progress: gaps `8`, open `7`, issues `0`, next `1084`.
