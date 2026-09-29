# Slice 1089: AE Web Grounded Generation Experience Hardening

## Goal

Make grounded-generation lifecycle and quality state observable without
content leakage, lock accessibility and race-control expectations, and include
the complete AE Web Node regression in the Full Gate.

## Implementation

- Added metadata-only generation lifecycle and presentation summaries to
  runtime diagnostics.
- Exposed phase, display mode, citation next action, and artifact-handoff state
  without prompt, response, source, provider, database, or storage material.
- Added deterministic accessibility and browser wiring smoke for generation
  controls, live status, cancellation guards, verified presentation, and
  responsive layout.
- Registered the smoke as an npm command and added both the smoke and complete
  AE Web Node regression to the Full Gate.
- Documented the Web regression requirement in the tiered development process.

## Verification

```bash
node --test apps/nex-ae-web/test/groundedGenerationExperienceSmoke.test.mjs \
  apps/nex-ae-web/test/runtimeDiagnostics.test.mjs \
  apps/nex-ae-web/test/groundedGenerationRecoveryWiring.test.mjs \
  apps/nex-ae-web/test/groundedGenerationPresentationWiring.test.mjs
npm test --prefix apps/nex-ae-web
node apps/nex-ae-web/scripts/runGroundedGenerationExperienceSmoke.mjs --summary
scripts/quality/run_slice_gate.sh --service nex-ae-web \
  --test tests/test_ae_web_grounded_generation_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py \
  --smoke scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py
```

## Observed Evidence

- Focused diagnostics, accessibility, and browser wiring regression:
  `12 passed`.
- Deterministic grounded-generation experience smoke: `PASS`, `3` controls,
  `3` initially disabled controls, `13` checks.
- AE Web Node regression: `281 passed`.
- Related Python audit, static, runtime, and gate regression: `47 passed`.
- Slice Gate: `273 passed`; statement coverage `100.00%`, branch coverage
  `100.00%` for the boundary-audit target.
- Contract validation: `108` schemas, `166` examples, `129` negative examples,
  and `7` OpenAPI documents.
- Boundary audit: `6` foundations, `8` planned gaps, `1` open gap,
  `0` implementation drifts; next Slice `1090`.
