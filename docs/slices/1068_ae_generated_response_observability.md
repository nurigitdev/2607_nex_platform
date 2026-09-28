# Slice 1068: AE Generated-Response Observability

## Goal

Expose useful generated-response persistence state to operators and workspace
activity without copying response content, storage refs, or lineage identifiers.

## Implementation

- Added idempotent `ae.generated_response.persisted` operational events after a
  READY response has succeeded in both private storage and chat persistence.
- Event details include only response type/size, lineage kind, citation/repair
  state, and boolean linkage indicators.
- Response text, hashes, storage refs, owner identity, provider details,
  retrieval IDs, CX IDs, and parent response IDs are excluded.
- Workspace async activities conditionally add generated-response availability,
  size, citation/repair, and retry-parent linkage metadata only when lineage is
  present. Existing pending/blocked activity shapes remain unchanged.
- Deterministic event IDs make replay emission idempotent and event-store
  failures remain non-blocking.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_generated_response_observability.py \
  --test tests/test_nex_ae_workspace_chat_orchestration.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generated_response_observability.py \
  --smoke scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py
```

## Evidence

- Slice Gate: `2475 passed`, `3 skipped` protected PostgreSQL tests.
- Coverage: statement `98.01%`, branch `95.96%`.
- Generated-response observability module: statement `100.00%`, branch
  `100.00%`.
- Contracts: schemas `101`, examples `159`, negative examples `122`, OpenAPI
  documents `7`.
- Success, replay idempotency, optional context, invalid lineage, store failure,
  route integration, and workspace activity privacy are covered.
- Boundary progress: gaps `8`, open `2`, resolved `6`, next Slice `1069`.
