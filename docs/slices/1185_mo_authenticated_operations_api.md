# Slice 1185: MO authenticated operations API foundation

## Goal

Expose the integrated operations snapshot through a service-authenticated,
bounded, privacy-safe API boundary before runtime/OpenAPI registration.

## Result

- Added `GET /api/v1/operations-snapshot` to the reusable MO API registrar.
- Reused MO service bearer authentication and rejected missing or unauthorized
  service claims.
- Added an optional `force_refresh` query control that reaches only the bounded
  refresh behavior implemented by the operations service.
- Converted unexpected composition failures to a stable redacted
  `503 application/problem+json` response without exception details.
- Kept this Slice as an isolated API foundation. Runtime registration and the
  canonical schema/OpenAPI update are atomic Slice 1187 work, avoiding
  deliberate contract drift between commits.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_operations_api.py
./.venv/bin/python scripts/smoke/run_mo_operations_api.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```

## Executed evidence

- API evidence passed with missing-auth `401`, authenticated `200`, four
  sources, three capabilities, and zero private fields.
- The API module reached `100%` statement and branch coverage, including safe
  `503` failure projection and explicit refresh propagation.
- NeX-MO Slice Gate passed `891` tests with `3` protected PostgreSQL skips;
  aggregate statement coverage was `99.86%` and branch coverage was `99.49%`.
