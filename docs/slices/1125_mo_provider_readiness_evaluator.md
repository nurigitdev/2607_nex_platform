# Slice 1125: MO provider readiness evaluator

## Goal

Execute the capability probe plan and convert each active preflight observation
into a privacy-safe route-health state and aggregate provider readiness result.

## Result

- Mock mode evaluates registry state without network access.
- Live mode actively probes embedding, reranking, and generation using the
  existing provider preflight implementation.
- Timeout, network, throttling, upstream 5xx, and malformed-response failures
  become retryable `DEGRADED` observations.
- Missing configuration, expected-model mismatch, and ordinary 4xx responses
  become non-retryable `UNAVAILABLE` observations.
- Unexpected evaluator failures expose no exception detail and fail closed as
  `UNKNOWN`.
- Aggregate provider readiness is `READY` only when all three required routes
  pass active evaluation.

Slice Gate passed with 351 tests, statement coverage 99.64%, and branch
coverage 98.63%. Both changed executable scopes have 100% statement and branch
coverage. Contract validation passed with 109 schemas, 167 examples, 132
negative examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_readiness_evaluator.py \
  --cov=nex_mo.provider_readiness_evaluator \
  --cov=run_mo_provider_readiness_evaluator \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_readiness_evaluator.py --summary
```
