# Slice 1069: AE Generated-Response Contract Hardening

## Goal

Freeze the public generated-response lineage, private owner-response surface,
and durable READY handoff behavior as canonical contracts.

## Implementation

- Added strict `ae_generated_response_lineage.v1` and
  `ae_generated_response.v1` JSON Schemas.
- Lineage contains response identity, integrity, retrieval/citation, repair,
  and retry-parent metadata while forbidding raw content and storage refs.
- The owner response contract carries integrity-verified content only through
  the exact-owner API surface.
- READY refreshes now require `content_persisted_by_ae=true`; non-READY
  refreshes require `false`.
- AE OpenAPI `1.5.0` publishes the owner response route and canonical response
  components, and embeds metadata-only lineage in chat interactions.
- Positive runtime/examples and explicit raw-content/storage-ref negative
  fixtures keep schemas, implementation, and API documentation aligned.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_generated_response_contracts.py \
  --test tests/test_ae_async_chat_contracts.py \
  --smoke scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py
```

## Evidence

- Focused contract tests: `40 passed`.
- Contract validation: schemas `103`, examples `161`, negative examples `124`,
  OpenAPI documents `7`.
- Slice Gate: `2480 passed`, `3 skipped` protected PostgreSQL tests.
- Coverage: statement `98.01%`, branch `95.96%`.
- Generated-response API, handoff, lineage, observability, and storage modules:
  statement `100.00%`, branch `100.00%`.
- Boundary progress: gaps `8`, open `1`, resolved `7`, next Slice `1070`.
