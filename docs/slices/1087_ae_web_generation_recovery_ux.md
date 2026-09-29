# Slice 1087: AE Web Generation Recovery UX

## Goal

Expose server-backed cancellation, recovery inspection, and retry controls while
preventing stale polling work from overwriting newer browser actions.

## Implementation

- Added lifecycle state transitions for recovery plans and non-destructive
  action failures.
- Added a browser recovery coordinator for cancel, recovery inspection, and
  retry through a new child interaction.
- Added explicit cancel, recovery, and retry controls with accessible status
  feedback and stable responsive layout.
- Added an `AbortController` and run sequence guard so cancelled or superseded
  polling cannot update current UI state.
- Kept action summaries free of raw prompts, generated content, service tokens,
  provider endpoints, and database details.

## Verification

```bash
node --test apps/nex-ae-web/test/generationLifecycleState.test.mjs \
  apps/nex-ae-web/test/groundedGenerationRecovery.test.mjs \
  apps/nex-ae-web/test/groundedGenerationRecoveryWiring.test.mjs \
  apps/nex-ae-web/test/groundedGenerationWorkflow.test.mjs
npm test --prefix apps/nex-ae-web
scripts/quality/run_slice_gate.sh --service nex-ae-web \
  --test tests/test_ae_web_grounded_generation_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py \
  --smoke scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py
```

## Observed Evidence

- Focused lifecycle, workflow, recovery, and UI wiring regression: `24 passed`.
- AE Web Node regression: `269 passed` before the final focused polling-race
  case; that added case also passed in the focused run.
- Related Python audit/static regression: `28 passed`.
- Slice Gate: `273 passed`; statement coverage `100.00%`, branch coverage
  `100.00%` for the boundary-audit target.
- Contract validation: `108` schemas, `166` examples, `129` negative examples,
  and `7` OpenAPI documents.
- Boundary audit: `6` foundations, `8` planned gaps, `3` open gaps,
  `0` implementation drifts; next Slice `1088`.
