# Slice 1123: MO provider readiness domain and projection

## Goal

Define immutable provider route-health and aggregate readiness models with a
strict privacy-safe public projection before any network probe is introduced.

## Result

- Route health has four explicit states: `READY`, `DEGRADED`, `UNAVAILABLE`,
  and `UNKNOWN`.
- Aggregate readiness requires one ready route for each required capability.
- Missing, degraded, unavailable, or stale route observations fail closed as
  `NOT_READY`.
- Mock readiness is deterministic, network-free, and derived from the existing
  route registry.
- Projection fields are allow-listed and omit endpoints, credentials, model
  paths, process commands, and provider payloads.
- The existing provider projection module remains the single owner of public
  route, profile, route-health, and readiness projections.

Slice Gate passed with 325 tests, statement coverage 99.61%, and branch
coverage 98.48%. All three changed scopes have 100% statement and branch
coverage. Contract validation passed with 109 schemas, 167 examples, 132
negative examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_readiness_domain.py \
  --cov=nex_mo.provider_readiness \
  --cov=nex_mo.provider_projection \
  --cov=run_mo_provider_readiness_domain \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_readiness_domain.py --summary
```
