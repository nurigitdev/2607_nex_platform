# Slice 1088: AE Web Verified Grounded Response

## Goal

Make AE's admitted retrieval projection, owner-verified response, citation
workflow, and repaired-response review the only inputs to generated-answer
presentation and artifact handoff.

## Implementation

- Preserved metadata-only retrieval, quality, and citation workflow projections
  in the grounded-generation browser client.
- Added a presentation coordinator that explicitly handles validated response,
  repaired-response review, quality-attention, active, failed, and unavailable
  states.
- Removed the duplicate standalone retrieval request from chat submission and
  reused the retrieval projection returned by AE admission.
- Blocked response text and artifact handoff unless owner verification and the
  citation workflow both permit presentation.
- Loaded repaired-response review through its owner-scoped client and attached
  the existing decision state before rendering.

## Verification

```bash
node --test apps/nex-ae-web/test/groundedGenerationClient.test.mjs \
  apps/nex-ae-web/test/groundedGenerationPresentation.test.mjs \
  apps/nex-ae-web/test/groundedGenerationPresentationWiring.test.mjs \
  apps/nex-ae-web/test/groundedGenerationWorkflow.test.mjs
npm test --prefix apps/nex-ae-web
scripts/quality/run_slice_gate.sh --service nex-ae-web \
  --test tests/test_ae_web_grounded_generation_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py \
  --smoke scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py
```

## Observed Evidence

- Focused client, workflow, presentation, and wiring regression: `21 passed`.
- AE Web Node regression: `277 passed`.
- Related Python audit/static regression: `28 passed`.
- Slice Gate: `273 passed`; statement coverage `100.00%`, branch coverage
  `100.00%` for the boundary-audit target.
- Contract validation: `108` schemas, `166` examples, `129` negative examples,
  and `7` OpenAPI documents.
- Boundary audit: `6` foundations, `8` planned gaps, `2` open gaps,
  `0` implementation drifts; next Slice `1089`.
