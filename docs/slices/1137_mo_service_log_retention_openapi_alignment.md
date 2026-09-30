# Slice 1137: MO service-log retention OpenAPI alignment

## Goal

Document the three shared service-log retention operations already mounted by
the MO runtime, including purge controls, history filters, and canonical
execution evidence.

## Result

- Added protected purge, history-list, and history-detail operations.
- Documented bounded purge controls, history filters, path parameters, and
  standard authorization, validation, conflict, not-found, and store failures.
- Bound execution and history entry projections to the existing common
  canonical retention schemas.
- Runtime behavior and database schema are unchanged.
- Closed three drift findings; only the public service root remains before the
  runtime/OpenAPI parity guard can require zero drift.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./.venv/bin/pytest -q \
  tests/test_mo_log_retention_openapi_contract.py \
  tests/test_mo_contract_api_drift_audit.py
./.venv/bin/python \
  scripts/smoke/run_mo_log_retention_openapi_contract.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_log_retention_openapi_contract.py
```

## Quality Evidence

- Focused regression: `31 passed`.
- Slice Gate: `437 passed`.
- Statement coverage: `99.67%` (threshold `95%`).
- Branch coverage: `98.73%` (threshold `94%`).
- Contract validation: `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Drift evidence: `3/3` retention operations and `4/4` components documented;
  `1` root-route drift remains for Slice 1138.
