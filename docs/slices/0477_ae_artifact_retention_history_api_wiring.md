# Slice 0477: AE artifact retention history API wiring

Expose the retention execution history read-model through an authenticated AE
API route.

## Changes

- Added `GET /api/v1/artifact-retention/executions`.
- Wired tenant/workspace/owner scope, mode, execution status, and limit query
  validation to the Slice 0476 history filter.
- Wrapped persisted history records into the metadata-only history collection
  contract before returning responses.
- Added regression coverage for query filtering, unauthorized access, missing
  scope, invalid mode, and raw execution payload exclusion.

## Decisions

- The API returns collection/items rather than persisted records so operators can
  inspect execution history without receiving the full saved purge execution
  JSON.
- Store contracts remain record-oriented; the HTTP layer owns response shaping.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
