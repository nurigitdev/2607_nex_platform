# Slice 1086: AE Web Generation Progress Wiring

## Goal

Replace local chat success fabrication with actual AE asynchronous interaction
admission, bounded progress polling, verified response loading, and
citation-quality gating.

## Implementation

- Added an owner-neutral request builder that submits workspace, chat,
  document-scope, and asynchronous generation intent to the same-origin AE API.
- Added bounded polling driven by AE progress projections, with explicit active,
  completed, failed, and interrupted outcomes.
- Loaded completed content only through AE refresh and generated-response
  routes, then loaded citation quality before enabling artifact handoff.
- Rewired the composer to render server-derived response content and progress
  events. Failed or still-active work no longer becomes synthetic success.
- Kept fetch-mode artifact export disabled unless an actual artifact handoff is
  present; deterministic local artifact creation remains mock-only.

## Verification

```bash
node --test apps/nex-ae-web/test/groundedGenerationClient.test.mjs \
  apps/nex-ae-web/test/groundedGenerationWorkflow.test.mjs
npm test --prefix apps/nex-ae-web
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_ae_web_grounded_generation_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py \
  --smoke scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py
```

## Observed Evidence

- Focused grounded-generation client/workflow regression: `13 passed`.
- AE Web Node regression: `260 passed`.
- Related Python audit/static regression: `28 passed`.
- Checkpoint Gate: `8277 passed`, `5 skipped`; statement coverage
  `98.67%`, branch coverage `96.69%`.
- Focused boundary-audit coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `108` schemas, `166` examples, `129` negative
  examples, and `7` OpenAPI documents.
- Boundary audit: `6` foundations, `8` planned gaps, `4` open gaps,
  `0` implementation drifts; next Slice `1087`.
