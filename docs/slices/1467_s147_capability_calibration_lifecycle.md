# Slice 1467: S147 Capability Calibration Lifecycle

## Outcome

- Added separate embedding, reranking, and generation calibration metric
  contracts under one model-independent lifecycle.
- Bound profiles to the exact identity, request shape, dataset, feature schema,
  policy, sample count, metrics, evaluation window, and profile digest.
- Required exact revision readiness before activation and rejected stale,
  mismatched, undersampled, incomplete, or quality-failing profiles.
- Made revision changes and explicit retirement yield
  `CALIBRATION_REQUIRED`; thresholds and profiles are never copied silently.

Slice 1468 composes revision readiness, ACTIVE calibration, canary budgets,
traffic ceilings, and state transitions, then runs the fifth-Slice Checkpoint
Gate.

## Verification

- Focused regression: `17 passed`; calibration lifecycle and smoke
  statement/branch coverage `100.00%`.
- MO Slice Gate: `1,171 passed`, `6 skipped`, statement `99.85%`, branch
  `99.32%`.
- Contract validation remained `166/228/196/7`; calibration smoke passed
  `12/12` with three ACTIVE profiles, one quality rejection, and one
  revision-change recalibration requirement.
