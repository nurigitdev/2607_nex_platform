# Slice 1129: MO provider route-health API and contract

## Goal

Expose the cached provider readiness snapshot through one authenticated,
privacy-safe service API with canonical JSON Schema and OpenAPI coverage.

## Result

- `GET /api/v1/provider-route-health` requires a valid `nex-mo` service claim.
- The query returns HTTP 200 for ready and non-ready provider states so
  operators can inspect route health; authentication failures return 401.
- Existing provider routes and route health share one extracted authorization
  boundary.
- The canonical schema covers mock/live/unknown modes, cache lifecycle states,
  aggregate counts, and per-capability health.
- `additionalProperties: false` plus a registered negative fixture rejects
  provider endpoint leakage.
- OpenAPI now declares the operation, bearer security, success schema, and its
  canonical contract path.
- The S111 contract drift audit is updated to the new 19 runtime operations,
  10 OpenAPI operations, and 8 MO schemas without hiding remaining drift.

Slice Gate passed with 398 tests, statement coverage 99.67%, and branch
coverage 98.73%. New auth, API, contract-audit, main wiring, and smoke scopes
have 100% statement coverage; all but the established provider composition
module also have 100% branch coverage, while that module remains at 97.62%.
Contract validation passed with 110 schemas, 168 examples, 133 negative
examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_readiness_api.py \
  tests/test_mo_contract_api_drift_audit.py \
  --cov=nex_mo.provider_auth \
  --cov=nex_mo.provider_readiness_api \
  --cov=nex_mo.contract_api_drift_audit \
  --cov=run_mo_provider_route_health_api \
  --cov-branch --cov-report=term-missing

./.venv/bin/python scripts/quality/validate_contracts.py
./.venv/bin/python scripts/smoke/run_mo_provider_route_health_api.py --summary
```
