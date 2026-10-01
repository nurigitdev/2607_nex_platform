# Slice 1187: MO operations contract and privacy hardening

## Goal

Expose the integrated MO operations snapshot through the authenticated runtime
without allowing API, OpenAPI, canonical schema, or privacy behavior to drift.

## Result

- Registered `GET /api/v1/operations-snapshot` in the MO application and wired
  the existing catalog, readiness, durable telemetry, and runtime observation
  services into one read-only composition service.
- Added the canonical `mo_operations_snapshot.v1` JSON Schema, a valid ready
  example, and a negative API-key leak fixture.
- Added the secured OpenAPI operation and canonical component marker.
- Raised the exact runtime/OpenAPI inventory to 28 operations, including 24
  authenticated operations and 20 canonical MO components, with zero drift.
- Kept the snapshot ephemeral: no operations snapshot table or migration was
  added, and force refresh remains bounded to readiness/runtime probes.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_operations_contract.py tests/test_mo_operations_api.py tests/test_mo_contract_api_drift_audit.py tests/test_mo_runtime_openapi_parity_guard.py
./.venv/bin/python scripts/quality/validate_contracts.py
./.venv/bin/python scripts/smoke/run_mo_operations_contract.py --summary
./.venv/bin/python scripts/smoke/run_mo_runtime_openapi_parity_guard.py --summary
./.venv/bin/python scripts/smoke/run_mo_contract_api_drift_audit.py --summary
scripts/quality/run_slice_gate.sh
```

## Executed evidence

- Focused contract and runtime tests passed `17` tests.
- Contract validation passed `129` schemas, `187` positive examples, `155`
  negative examples, and `7` OpenAPI documents.
- Operations contract evidence passed `9/9` checks, including schema,
  authentication, runtime registration, documentation, and privacy guards.
- Runtime/OpenAPI parity passed at `28/28` operations, `24/24` secured
  operations, `20` canonical components, and zero drift.
- The Slice Gate passed `911` tests with `3` protected PostgreSQL smoke skips
  and `1` warning in 72 seconds; statement coverage was `99.86%` and branch
  coverage was `99.50%`.
