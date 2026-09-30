# Slice 1179: MO Catalog Lifecycle Contract Hardening

## Scope

- Register the seven authenticated catalog and alias lifecycle operations on the
  NeX-MO runtime application.
- Add eight canonical JSON Schemas for catalog entries, catalog collections,
  registrations, transitions, alias bindings, alias collections, activations,
  and rollbacks.
- Add indexed positive and negative fixtures for every new schema.
- Extend the NeX-MO OpenAPI document and runtime parity guard from 20 to 27
  operations without weakening the historical S114 baseline.
- Keep audit actor identity server-derived and exclude endpoints, credentials,
  model paths, database URLs, and `changed_by` from public projections.

## Contract decisions

- Mutation request schemas use `additionalProperties: false`.
- Alias activation allows expected revision `0` for a newly introduced alias;
  rollback requires revision `1` or greater.
- Catalog transition requests expose only `ACTIVE` and `RETIRED` targets.
- All seven operations require the existing NeX-MO service bearer claim.
- Runtime/OpenAPI equality, operation ID uniqueness, canonical component
  binding, and positive/negative fixture coverage remain fail-closed checks.

## Evidence

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
./.venv/bin/python scripts/smoke/run_mo_catalog_lifecycle_contracts.py --summary
./.venv/bin/python scripts/smoke/run_mo_runtime_openapi_parity_guard.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```

Expected deterministic evidence is `27/27` runtime/OpenAPI operations, seven
authenticated catalog lifecycle rejections without a valid claim, zero contract
drift, complete fixtures, and no private field exposure.
