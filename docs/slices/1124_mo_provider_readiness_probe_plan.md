# Slice 1124: MO provider readiness probe plan

## Goal

Build one capability-specific readiness probe plan for embedding, reranking,
and generation without duplicating the existing remote provider configuration
or exposing provider-private values.

## Result

- Mock mode creates three deterministic local probe targets and performs no
  network setup while retaining each registry route status for evaluation.
- Live mode combines the existing preflight request definition with the
  existing execution deployment and model identity for each capability.
- Missing live endpoints remain explicit unconfigured targets so the health
  evaluator can fail closed in Slice 1125.
- Route lookup rejects missing and duplicate capability routes.
- Public summaries are allow-listed and omit endpoints, credentials, model
  paths, private preflight configuration, and request or response payloads.

Slice Gate passed with 334 tests, statement coverage 99.63%, and branch
coverage 98.55%. Both changed executable scopes have 100% statement and branch
coverage. Contract validation passed with 109 schemas, 167 examples, 132
negative examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_readiness_plan.py \
  --cov=nex_mo.provider_readiness_plan \
  --cov=run_mo_provider_readiness_plan \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_readiness_plan.py --summary
```
