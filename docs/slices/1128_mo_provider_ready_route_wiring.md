# Slice 1128: MO provider-aware `/ready` wiring

## Goal

Extend the shared readiness composition without changing the four other
service shells, then wire MO database and provider readiness together.

## Result

- `build_service_app` accepts optional readiness checks while preserving the
  database-only default.
- Additional checker exceptions and malformed results fail closed with a
  stable error code and no exception detail.
- MO `/ready` evaluates database first and the provider-route check second.
- MO returns HTTP 200 only when both checks pass; either failure returns 503.
- The shared `ProviderReadinessService` instance is attached to app state for
  the authenticated route-health API in Slice 1129.
- The earlier MO resilience audit now marks provider-aware readiness as
  implemented and removes that resolved runtime gap.

Slice Gate passed with 410 tests, statement coverage 99.69%, and branch
coverage 98.77%. All four changed executable scopes have 100% statement and
branch coverage. Contract validation passed with 109 schemas, 167 examples,
132 negative examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_runtime_app.py \
  tests/test_mo_provider_readiness_ready_route.py \
  --cov=nex_runtime.app \
  --cov=nex_mo.main \
  --cov=run_mo_provider_ready_route \
  --cov-branch --cov-report=term-missing

./.venv/bin/python scripts/smoke/run_mo_provider_ready_route.py --summary
```
