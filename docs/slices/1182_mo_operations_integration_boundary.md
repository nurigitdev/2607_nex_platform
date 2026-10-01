# Slice 1182: MO operations integration and protected live acceptance boundary

## Goal

Freeze S119 ownership, source composition, status precedence, persistence,
privacy, and protected live acceptance boundaries before runtime changes.

## Result

- Selected catalog/alias state, provider readiness, durable telemetry, and
  GPU/model runtime observation as four existing service-owned facts.
- Required aggregate status precedence `UNAVAILABLE > DEGRADED > UNKNOWN >
  READY`; missing, stale, or failed required sources cannot produce readiness.
- Kept refresh explicit, bounded, and service-authenticated.
- Added no table. S119 reuses the catalog, alias, and telemetry persistence
  already owned by NeX-MO.
- Required actual protected acceptance against `nex_mo_user@nex_mo_test` and
  all three DGX vLLM capabilities, with bounded seed and targeted cleanup.
- Kept endpoints, credentials, SSH targets, paths, database URLs, prompts, and
  provider request/response payloads outside operations projections and
  evidence files.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_operations_integration_boundary.py
./.venv/bin/python \
  scripts/smoke/run_mo_operations_integration_boundary.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```

## Decision

S119 is an integration and acceptance requirement, not another storage layer.
It composes existing MO-owned facts and proves their joint behavior through a
protected PostgreSQL and DGX profile without making live calls part of default
regression.

## Executed evidence

- Boundary evidence passed with `8/8` source boundaries, four operational
  sources, three required capabilities, zero new tables, and zero issues.
- NeX-MO Slice Gate passed `840` tests with `3` protected PostgreSQL skips.
- Statement coverage was `99.85%` and branch coverage was `99.44%`; contract
  validation passed `128` schemas, `186` positive examples, `154` negative
  examples, and `7` OpenAPI documents.
