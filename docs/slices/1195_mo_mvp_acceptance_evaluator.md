# Slice 1195: MO MVP acceptance evaluator

## Goal

Evaluate MO MVP acceptance evidence deterministically, reject missing or stale
proof, and expose only privacy-safe gate status and reason codes.

## Evaluation Rules

- All nine policy gates must pass within the configured freshness window.
- Missing, skipped, malformed, future-dated, or stale evidence blocks.
- Regression, statement coverage, and branch coverage use policy thresholds.
- PostgreSQL must prove `nex_mo_test` and zero cleanup residue.
- Live acceptance must prove the three expected models, three ready
  capabilities, zero failed calls, and explicit BF16 runtime configuration.
- Privacy/runbook inventory and a sealed NeX-OA handoff are blocking.
- The report excludes raw evidence and derives a deterministic SHA-256
  acceptance ID from policy, evaluation time, and gate statuses.
- Unknown gate evaluators block rather than silently pass.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_mo_mvp_acceptance_evaluation.py \
  tests/test_mo_mvp_acceptance_evaluator.py
./.venv/bin/python \
  scripts/smoke/run_mo_mvp_acceptance_evaluator.py --summary
```

## Result

- Deterministic acceptance: `ACCEPTED`.
- Blocking gates passed: `9/9`.
- Raw evidence included: `false`.
- Next Slice: `1196`.
- Slice Gate: `982 passed`, `5 skipped`; statement coverage `99.87%`, branch
  coverage `99.54%`; evaluator and smoke scopes statement/branch `100%`.
- Contract validation: schemas `129`, positive examples `187`, negative
  examples `155`, OpenAPI documents `7`.
