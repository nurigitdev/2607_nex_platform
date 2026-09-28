# Slice 1055: AE Owner-Scoped Citation-Quality API

## Goal

Expose the canonical citation-quality workflow only after authenticating the
AE caller and enforcing the persisted chat interaction's tenant/owner scope.

## Implementation

- Added `GET /api/v1/chat/interactions/{interaction_id}/citation-quality`.
- Reused the durable async job lineage and fetched the CX handoff with the
  persisted tenant and owner identifiers.
- Required a READY handoff with matching job and generation lineage before
  projecting citation quality.
- Mapped pending handoffs to a retryable `409` and upstream CX failures to the
  existing problem contract.

## Security And Privacy

- Browser users outside the exact tenant/owner scope receive `404` before any
  CX request is made.
- The endpoint returns metadata only; generation content and CX handoff
  content are not copied into the response.
- No database schema change, migration, or remote model provider is required.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_citation_quality_api.py \
  --test tests/test_nex_ae_citation_quality_workflow.py \
  --coverage-target services/nex-ae-api/nex_ae_api/citation_quality_workflow.py
```

## Observed Evidence

- Slice Gate: pass (`2386 passed`, `2` separately protected PostgreSQL smoke
  tests skipped).
- Statement coverage: `97.93%` (threshold `95%`).
- Branch coverage: `95.82%` (threshold `94%`).
- `citation_quality_workflow.py`: statement `100%`, branch `100%`.
- Contract validation: pass (`100` schemas, `156` positive examples, `119`
  negative examples, `7` OpenAPI documents).
- Cross-owner test confirmed `404` with zero CX handoff calls.
