# Slice 1169: MO runtime observability contract hardening

## Goal

Register runtime observability in the MO app and align its authenticated API,
canonical schema, fixtures, OpenAPI, privacy, operations, and parity guards in
one atomic contract change.

## Result

- Registered one process-local `RuntimeObservabilityService` and authenticated
  `GET /api/v1/model-runtime-observability` in the MO main app.
- Added canonical `mo_runtime_observability.v1` JSON Schema with strict
  top-level and per-model `additionalProperties: false` boundaries.
- Added indexed positive mock evidence and a negative SSH-target leak fixture.
- Added the OpenAPI operation, `force_refresh` query parameter, service bearer
  security, response component, and canonical schema marker.
- Advanced exact runtime/OpenAPI parity to `20/20`, protected operation
  security to `16/16`, MO canonical components to `11`, and MO schema fixture
  coverage to `18/18`.
- Updated deterministic contract HTTP smoke to validate the runtime snapshot as
  the eighth provider-operations response without network access.
- Confirmed S117 adds no database table; current GPU samples remain outside
  PostgreSQL.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_runtime_observability_contract.py \
  tests/test_mo_runtime_observability_api.py \
  tests/test_mo_contract_api_drift_audit.py \
  tests/test_mo_runtime_openapi_parity_guard.py \
  tests/test_mo_contract_http_smoke.py
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_observability_contract.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_runtime_observability_contract.py \
  --coverage-target \
  services/nex-mo/nex_mo/runtime_observability_contract.py \
  --smoke scripts/smoke/run_mo_runtime_observability_contract.py
```

## Quality evidence

- Slice Gate: `742 passed, 2 skipped`
- Statement coverage: `99.81%`
- Branch coverage: `99.26%`
- Changed-module coverage: statement `100%`, branch `100%`
- Contract validation: `120` schemas, `178` examples, `146` negative
  examples, and `7` OpenAPI documents
- Runtime observability contract: `9/9` checks passed with all `7`
  forbidden private fields absent
