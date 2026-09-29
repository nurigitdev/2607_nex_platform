# Slice 1084: AE Web Generation Lifecycle State

## Goal

Introduce a deterministic, privacy-safe lifecycle state and read model between
the grounded-generation client and AE Web rendering.

## Implementation

- Added explicit idle, admitting, active, completed, failed, and cancelled
  phases with validated interaction lineage.
- Projected bounded polling, progress, cancellation, retry, recovery, and
  terminal-state controls from AE client results.
- Admitted owner-visible response content only from owner-verified response or
  AE-persisted refresh results.
- Required both verified response and citation workflow approval before the
  artifact handoff read model becomes enabled.
- Kept generated content and raw transport exception details out of lifecycle
  summaries and diagnostics metadata.

## Verification

```bash
node --test apps/nex-ae-web/test/generationLifecycleState.test.mjs
npm test --prefix apps/nex-ae-web
scripts/quality/run_slice_gate.sh --service nex-ae-web \
  --test tests/test_ae_web_grounded_generation_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py \
  --smoke scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py
```

## Observed Evidence

- Focused lifecycle tests: `8 passed`.
- AE Web Node regression: `254 passed`.
- Slice Gate: `273 passed`; focused audit statement and branch coverage both
  `100.00%`.
- Contract Gate: `108` schemas, `166` positive examples, `129` negative
  examples, and `7` OpenAPI documents passed.
- Boundary progress: gaps `8`, open `6`, issues `0`, next `1085`.
