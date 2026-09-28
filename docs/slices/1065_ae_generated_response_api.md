# Slice 1065: AE Owner-Scoped Generated-Response API

## Goal

Expose durable generated response content only to the exact interaction owner
while keeping private storage references and local paths out of API responses.

## Implementation

- Added `GET /api/v1/chat/interactions/{interaction_id}/response` under the
  existing AE facade authorization boundary.
- Browser claims select the exact tenant and owner row before any private
  storage read; missing and cross-owner interactions share the same 404 shape.
- Response content is loaded through the generated-response storage adapter and
  rechecked against persisted byte size and SHA-256 before presentation.
- Public responses include safe canonical lineage but no logical storage ref or
  filesystem path.
- Missing content, tampering, invalid persisted lineage, and storage failures
  fail closed with stable error codes.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_generated_response_api.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generated_response_api.py \
  --smoke scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py
```

## Evidence

- Slice Gate: `2462 passed`, `3 skipped` protected PostgreSQL tests.
- Coverage: statement `98.00%`, branch `95.97%`.
- Generated-response API module: statement `100.00%`, branch `100.00%`.
- Contracts: schemas `101`, examples `159`, negative examples `122`, OpenAPI
  documents `7`.
- Exact-owner, cross-owner, missing, not-ready, unavailable, tampered, and
  lineage-drift paths are covered.
- Boundary progress: gaps `8`, open `5`, resolved `3`, next Slice `1066`.
