# Slice 0896: AG MVP acceptance contract and operations hardening

## Goal

Freeze the protected S90 operations projection in strict JSON Schema and
OpenAPI, including privacy-negative fixtures.

## Contract

- Added `mvp_acceptance.v1.schema.json` with exactly eight known gate IDs,
  bounded blocker arrays, enumerated reason codes, strict summary fields, and
  no additional properties.
- Added one accepted operations example and two otherwise-valid negative
  fixtures proving that raw evidence, database URLs, and credentials cannot be
  added to the response.
- Added only `GET /admin/v1/operations/mvp-acceptance` to OpenAPI. No request
  body, POST operation, or client-supplied evidence contract exists.
- OpenAPI components for the projection, gate result, and blocker are strict.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_mvp_acceptance_contracts.py
./.venv/bin/python scripts/quality/validate_contracts.py contracts
```

Observed verification:

```text
focused contract tests: 3 passed
contract validation: schemas=82 examples=133 negative_fixtures=97 openapi=7
aggregate regression: 6219 passed, 1 known warning
statement=75114/75995=98.840713204816%
branch=17572/18222=96.432883327845%
```
