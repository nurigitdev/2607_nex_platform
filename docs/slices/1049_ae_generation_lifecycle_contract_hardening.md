# Slice 1049: AE Generation Lifecycle Contract Hardening

## Goal

Publish canonical JSON Schema and OpenAPI contracts for S105 progress and
recovery APIs.

## Implementation

- Added strict `generation_progress.v1` and `generation_recovery_plan.v1`
  canonical JSON Schemas.
- Added queued and completed progress examples plus retry-as-child recovery
  evidence.
- Added negative fixtures for generated-content leakage, invalid completed
  percentage, and missing retry lineage requirements.
- Added progress and recovery GET paths to AE OpenAPI and linked canonical
  schema components.
- Advanced the AE OpenAPI version from `1.2.0` to `1.3.0`.
- Added runtime-to-schema parity and OpenAPI linkage regression tests.

## Decisions

- API responses remain strict snapshots with `additionalProperties: false`.
- Recovery remains read-only; mutation is represented by the existing retry
  endpoint.
- No database migration, PostgreSQL access, or remote provider is required.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_generation_lifecycle_contracts.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generation_progress.py
```

## Observed Evidence

- Focused lifecycle contract regression: `14 passed`; related OpenAPI
  compatibility regression: `28 passed`.
- Slice Gate: `2320 passed`, `1 skipped` protected PostgreSQL smoke.
- Repository coverage: statement `97.91%`, branch `95.76%`.
- Progress contract module coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `100` schemas, `156` examples, `119` negative
  examples, and `7` OpenAPI documents passed.
