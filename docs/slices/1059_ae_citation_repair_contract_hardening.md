# Slice 1059: AE Citation Repair Contract Hardening

## Goal

Freeze the owner-visible citation-quality and bounded repair workflow as a
canonical contract across persisted chat interactions and the AE API.

## Implementation

- Added strict `ae_citation_quality_workflow.v1` JSON Schema coverage for
  quality, bounded inline repair, separate operator remediation, privacy, and
  owner-scope metadata.
- Added validated, repaired, and attention-required positive fixtures.
- Added negative fixtures for raw output leakage, inconsistent workflow
  action, and disabled owner scope.
- Allowed the canonical workflow in asynchronous chat interaction generation
  summaries.
- Added `GET /api/v1/chat/interactions/{interaction_id}/citation-quality` and
  `AeCitationQualityWorkflow` to AE OpenAPI.
- Advanced the backwards-compatible AE API contract version to `1.4.0`.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_citation_quality_contracts.py \
  --test tests/test_ae_async_chat_contracts.py
```

## Observed Evidence

- Slice Gate: pass (`2409 passed`, `2` separately protected PostgreSQL smoke
  tests skipped).
- Statement coverage: `97.95%` (threshold `95%`).
- Branch coverage: `95.85%` (threshold `94%`).
- Contract validation: pass (`101` schemas, `159` positive examples, `122`
  negative examples, `7` OpenAPI documents).
- Focused contract regression: `40 passed`.
