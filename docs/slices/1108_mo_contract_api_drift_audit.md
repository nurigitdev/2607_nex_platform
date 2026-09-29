# Slice 1108: MO contract and API drift audit

## Goal

Compare the executable MO API with its OpenAPI document and schema fixture
coverage after the profile privacy repair.

## Result

- Runtime exposes 18 operations while `nex-mo.openapi.yaml` documents 9.
- Missing operations include provider telemetry, the service root, four shared
  job controls, and three shared log-retention operations.
- The three provider execution operations retain stale mock-only names or
  descriptions despite supporting mock and live modes.
- Existing provider operations lack request-body schemas, success response
  schemas, and explicit service-claim security declarations.
- All seven MO schemas have positive examples; four have negative fixtures and
  three still need negative coverage.
- The audit classifies 28 discrete drift items. S112 should close them in
  priority order without changing provider execution behavior.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_mo_contract_api_drift_audit.py --summary

./.venv/bin/pytest -q \
  tests/test_mo_contract_api_drift_audit.py \
  --cov=nex_mo.contract_api_drift_audit \
  --cov=run_mo_contract_api_drift_audit \
  --cov-branch --cov-report=term-missing
```
