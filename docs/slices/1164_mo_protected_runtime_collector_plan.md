# Slice 1164: MO protected runtime collector plan

## Goal

Build the private, fixed collection plan for mock and protected DGX runtime
observations without executing a remote command.

## Result

- Added a dedicated `NEX_MO_RUNTIME_OBSERVABILITY_MODE` with deterministic
  `mock` default and explicit `live` opt-in.
- Live planning requires a strictly validated `user@host` SSH target and uses
  a fixed Python-stdin collector protocol. No API field or environment variable
  can provide an arbitrary remote command.
- Planned unique generation, embedding, and reranking process ports with safe
  integer/range validation and operator overrides.
- Derived selected model identities and requested dtype from the canonical MO
  catalog instead of duplicating model policy.
- Kept SSH target and process ports in the private plan; the evidence
  projection exposes only mode, capability, model, and dtype summaries.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_runtime_observation_plan.py
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_observation_plan.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_runtime_observation_plan.py \
  --coverage-target services/nex-mo/nex_mo/runtime_observability_plan.py \
  --smoke scripts/smoke/run_mo_runtime_observation_plan.py
```

## Quality Evidence

- Focused regression: `10 passed` with statement/branch `100%/100%`.
- Slice Gate: `661 passed`, `2` protected PostgreSQL skips.
- Repository coverage: statement `99.78%`, branch `99.17%`; changed plan scope
  `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Deterministic plan evidence passed six checks for `3/3` targets, selected
  models, and requested dtypes with private target and port data omitted.
