# Slice 1122: MO provider readiness and route-health boundary

## Goal

Freeze the S113 provider-aware readiness, route-health, caching, privacy, and
persistence decisions before changing the public `/ready` behavior.

## Result

- Six existing boundaries are assigned to ordered S113 implementation slices.
- Mock mode remains deterministic and network-free.
- Live mode requires active preflight success for embedding, reranking, and
  generation before MO may report provider readiness.
- Provider checks compose with the existing database check; every required
  check must pass.
- Provider observations use a bounded process-local TTL cache. Stale snapshots
  never satisfy readiness.
- Endpoints, credentials, model paths, process commands, and request/response
  payloads are forbidden from readiness projections.
- S113 introduces no database table. Durable aggregate telemetry remains S116
  scope and high-frequency runtime/GPU metrics remain outside PostgreSQL.

Slice Gate passed with 313 tests, statement coverage 99.58%, and branch
coverage 98.37%. Both changed scopes have 100% statement and branch coverage.
Contract validation passed with 109 schemas, 167 examples, 132 negative
examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_readiness_boundary.py \
  --cov=nex_mo.provider_readiness_boundary \
  --cov=run_mo_provider_readiness_boundary \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_readiness_boundary.py --summary
```
