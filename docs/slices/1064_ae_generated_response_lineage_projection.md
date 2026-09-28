# Slice 1064: AE Generated-Response Lineage Projection

## Goal

Persist canonical generated-response lineage with an AE chat interaction while
keeping raw response content and storage references outside PostgreSQL.

## Implementation

- Added deterministic response IDs derived from interaction ID, CX generation
  ID, and response content SHA-256.
- Added a strict `ae_generated_response_lineage.v1` projection covering CX job
  lineage, retrieval package, structured draft, citation workflow, bounded
  repair, and retry parent references.
- Added attach/read helpers for `generation.generated_response` in the existing
  `ae_chat_interactions.generation_summary` JSON column; no table was added.
- Kept raw content and logical storage references out of persisted and public
  lineage. Storage metadata is reconstructed only inside the storage boundary.
- Added idempotent attachment and conflict detection for lineage drift.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_generated_response_lineage.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generated_response_lineage.py \
  --smoke scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py
```

## Evidence

- Slice Gate: `2455 passed`, `3 skipped` protected PostgreSQL tests.
- Coverage: statement `97.99%`, branch `95.95%`.
- Lineage module coverage: statement `100.00%`, branch `100.00%`.
- Contracts: schemas `101`, examples `159`, negative examples `122`, OpenAPI
  documents `7`.
- SQLite regression verifies `generation_summary` round-trip persistence.
- The stored projection contains neither response text nor `ae://` storage
  references.
- Boundary progress: gaps `8`, open `6`, resolved `2`, next Slice `1065`.
