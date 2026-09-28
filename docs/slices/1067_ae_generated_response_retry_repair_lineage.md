# Slice 1067: AE Generated-Response Retry and Repair Lineage

## Goal

Unify asynchronous retry and bounded citation-repair lineage with the durable
AE generated-response projection.

## Implementation

- Retry orchestration now always records a `parent_response_id` field.
- When the parent has a durable generated response, the child retry links its
  exact response ID. When the parent failed before producing content, the value
  is `null` while the parent interaction/job/CX generation lineage remains.
- The private retry-lineage fallback and normal recovery path now share one
  validated builder instead of assembling subtly different records.
- Generated retry responses accept the truthful no-parent-response case while
  still requiring a parent interaction.
- Bounded citation repair remains the final content of the same CX generation;
  it does not create a synthetic child generation or a second response identity
  for unchanged content.
- The existing chat interaction JSON Schema/OpenAPI retry object temporarily
  permits the nullable field; Slice 1069 will freeze the complete S107 contract.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_generation_recovery_orchestration.py \
  --test tests/test_ae_async_chat_cancel_retry.py \
  --test tests/test_nex_ae_generated_response_lineage.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generation_recovery.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generated_response_lineage.py \
  --smoke scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py
```

## Evidence

- Slice Gate: `2471 passed`, `3 skipped` protected PostgreSQL tests.
- Coverage: statement `98.00%`, branch `95.97%`.
- Generation recovery and generated-response lineage modules: statement
  `100.00%`, branch `100.00%` each.
- Contracts: schemas `101`, examples `159`, negative examples `122`, OpenAPI
  documents `7`.
- Retry lineage covers parents with and without responses, invalid parent
  lineage, invalid projections, and child response preparation.
- Repair lineage proves stable response identity for the same final content.
- Boundary progress: gaps `8`, open `3`, resolved `5`, next Slice `1068`.
