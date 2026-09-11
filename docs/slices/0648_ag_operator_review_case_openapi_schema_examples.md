# Slice 0648: AG Operator Review Case OpenAPI/Schema/Examples Freeze

## Intent

Freeze the AG operator review case/action contract surface introduced in
Slices 0642-0647 before adding PostgreSQL smoke evidence and S65 closure.

## Scope

- Add JSON Schema coverage for case detail, list, create mutation, and action
  mutation responses under `operator_review_case.v1`.
- Add a dedicated rollup schema for `/admin/v1/operator-review/cases/rollups`.
- Add positive contract examples for list, mutation, action mutation, and
  rollup responses.
- Add negative fixtures that reject raw resolution comments and rollup action
  comment leakage.
- Publish the case/action route family in `contracts/openapi/nex-ag.openapi.yaml`.

## Boundary Notes

- Case and action comments remain hash plus bounded preview only.
- Rollup attention items carry target refs, status, priority, reason codes, and
  recommended actions, but no raw comments or storage/provider payloads.
- Case action history remains operational-event-first; the case table stores
  only the latest safe action summary in metadata.
- No database table is added in this slice.

## Evidence

- `python scripts/quality/validate_contracts.py`
- Targeted AG case regression tests
- Full quality gate
