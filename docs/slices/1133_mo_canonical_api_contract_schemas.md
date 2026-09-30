# Slice 1133: MO canonical API contract schemas

## Goal

Add canonical JSON Schemas for the actual MO public provider API wire shapes,
without conflating them with the OpenAI-compatible downstream DGX contracts.

## Result

- Added route-list, profile-list, telemetry-snapshot, embedding, rerank, and
  generation request/response schemas: nine canonical schemas in total.
- Added one valid and one invalid indexed fixture for every new schema so the
  quality gate remains complete while S114 progresses.
- Validated all six authenticated MO provider runtime surfaces against their
  response schemas in deterministic mock mode; all three POST request payloads
  are also validated before dispatch.
- Preserved the existing `compatible_*` schemas exclusively for downstream
  provider protocol compatibility.
- Added no database table and made no DGX request.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./.venv/bin/pytest -q tests/test_mo_canonical_api_contract_schemas.py
./.venv/bin/python \
  scripts/smoke/run_mo_canonical_api_contract_schemas.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_canonical_api_contract_schemas.py
```

## Quality Evidence

- Runtime contract smoke: `6/6` surfaces, `3` request schemas, and `6`
  response schemas passed.
- Focused regression: `14 passed` across closure boundary, historical drift
  audit, and canonical runtime schema evidence.
- Slice Gate: `421 passed`; statement coverage `99.67%`; branch coverage
  `98.73%`.
- Contract validation: `119` schemas, `177` positive examples, `142` negative
  examples, and `7` OpenAPI documents.
- The S111 drift baseline remains `28`; the MO schema inventory increased from
  `8` to `17` with matching indexed fixtures rather than hiding any gap.
