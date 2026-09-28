# Slice 1066: AE Async Generated-Response Handoff Integration

## Goal

Make a READY CX asynchronous handoff durable in both AE private response
storage and the existing owner-scoped chat interaction record.

## Implementation

- READY refresh now writes validated response content to private storage and
  persists canonical generated-response lineage in `generation_summary`.
- Pending and blocked refreshes retain the metadata-only path and do not create
  response content.
- Repeated READY refreshes reuse the deterministic response ID and storage ref.
- A new payload is compensating-deleted if chat persistence fails. Replays with
  an already persisted lineage do not delete the prior owner response when a
  subsequent database write fails.
- Refresh responses now set `content_persisted_by_ae=true` only after both
  private content and lineage persistence succeed.
- SQLite restart regression proves that durable chat lineage can recover the
  response through the private storage adapter without another CX handoff.

## Verification

```bash
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_nex_ae_generated_response_handoff.py \
  --test tests/test_ae_async_chat_refresh.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generated_response_handoff.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generated_response_lineage.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generated_response_storage.py \
  --smoke scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py
```

## Evidence

- Checkpoint Gate: `8076 passed`, `3 skipped` protected PostgreSQL tests.
- Coverage: statement `98.67%`, branch `96.66%`.
- Handoff, lineage, and storage target modules: statement `100.00%`, branch
  `100.00%` each.
- Contracts: schemas `101`, examples `159`, negative examples `122`, OpenAPI
  documents `7`.
- READY success, replay, restart read, storage failure, database compensation,
  compensation failure, and inconsistent storage-ref paths are covered.
- Boundary progress: gaps `8`, open `4`, resolved `4`, next Slice `1067`.
