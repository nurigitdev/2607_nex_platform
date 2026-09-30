# Slice 1127: MO provider readiness composition service

## Goal

Compose the probe plan, evaluator, and TTL cache behind one fail-closed MO
service boundary that can be attached to the shared `/ready` route next.

## Result

- One service now owns plan construction, active evaluation, TTL reuse, forced
  refresh, and privacy-safe readiness-check projection.
- Provider configuration changes invalidate prior cached observations,
  including endpoint and credential rotation, without projecting either value.
- `NEX_MO_PROVIDER_READINESS_TTL_SECONDS` supports a bounded 1-300 second TTL
  with a 30-second default.
- Invalid mode, TTL, timestamp, or plan construction returns a stable
  `PROVIDER_READINESS_EVALUATION_FAILED` check without exception details.
- Mock mode remains network-free and live provider failures retain safe
  capability-level route health.

Slice Gate passed with 380 tests, statement coverage 99.67%, and branch
coverage 98.74%. Both changed executable scopes have 100% statement and branch
coverage. Contract validation passed with 109 schemas, 167 examples, 132
negative examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_readiness_service.py \
  --cov=nex_mo.provider_readiness_service \
  --cov=run_mo_provider_readiness_service \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_readiness_service.py --summary
```
