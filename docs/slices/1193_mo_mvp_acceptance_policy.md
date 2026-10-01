# Slice 1193: MO MVP acceptance policy

## Goal

Define the validated, fail-closed policy that controls NeX-MO service MVP
acceptance and the transition to NeX-OA.

## Policy

- Nine evidence gates are blocking and do not allow skipped evidence.
- Evidence must be server-derived and no older than 24 hours.
- Full regression requires at least 9,000 passing tests and zero failures.
- Default coverage thresholds are statement 98% and branch 96%; environment
  overrides cannot weaken the project floors of 95% and 85%.
- Actual PostgreSQL evidence must target `nex_mo_test` and leave zero residue.
- Embedding, reranking, and generation must use the expected live model
  identities with no failed calls and explicit BF16 runtime evidence.
- Privacy/runbook and sealed OA transition handoff evidence are blocking.
- Production activation, external metrics storage, load, and disaster recovery
  remain advisory and do not silently weaken blocking gates.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_mo_mvp_acceptance.py \
  tests/test_mo_mvp_acceptance_policy.py
./.venv/bin/python \
  scripts/smoke/run_mo_mvp_acceptance_policy.py --summary
```

## Result

- Policy ID: `mo-mvp-acceptance-v1`.
- Blocking gates: `9/9`.
- Evidence freshness: 24 hours.
- Next Slice: `1194`.
- Slice Gate: `945 passed`, `5 skipped`; statement coverage `99.87%`, branch
  coverage `99.51%`; policy and smoke scopes both statement/branch `100%`.
- Contract validation: schemas `129`, positive examples `187`, negative
  examples `155`, OpenAPI documents `7`.
