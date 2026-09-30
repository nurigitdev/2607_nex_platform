# Slice 1135: MO provider OpenAPI contract hardening

## Goal

Align every protected MO provider business operation with its actual runtime
request, response, security, and mode-neutral behavior.

## Result

- Added provider telemetry to the MO OpenAPI and documented all seven provider
  business paths.
- Added service-bearer security and canonical success projections to every
  protected provider operation.
- Added canonical request bodies for embedding, rerank, and generation.
- Replaced mock-only POST operation names and descriptions with mode-neutral
  contracts valid for both deterministic mock and live provider modes.
- Bound nine OpenAPI components to their canonical JSON Schema files.
- Closed `17` drift findings; only the eight shared root, job-control, and
  service-log retention operations remain.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./.venv/bin/pytest -q \
  tests/test_mo_provider_openapi_contract.py \
  tests/test_mo_contract_api_drift_audit.py \
  tests/test_mo_contract_api_closure_boundary.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_openapi_contract.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_openapi_contract.py
```

## Quality Evidence

- Provider OpenAPI evidence: `7` paths, `9` canonical components, `17` drift
  findings closed, `8` remaining.
- Focused regression: `23 passed`.
- Slice Gate: `429 passed`; statement coverage `99.67%`; branch coverage
  `98.73%`.
- Contract validation: `119` schemas, `177` positive examples, `145` negative
  examples, and `7` OpenAPI documents.
