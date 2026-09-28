# Slice 1054: AE Citation-Quality Workflow Projection

## Goal

Define one privacy-safe AE projection that explains CX grounded-response
quality, bounded inline citation repair, and the separate operator remediation
boundary.

## Implementation

- Added strict `ae_citation_quality_workflow.v1` construction and validation.
- Classified owner-visible workflow state as `NOT_REQUIRED`, `VALIDATED`,
  `REPAIRED`, or `ATTENTION_REQUIRED`.
- Kept bounded inline repair distinct from the existing separate remediation
  handoff lifecycle.
- Extracted the existing grounded-response quality mapping into the canonical
  workflow module while preserving the synchronous chat contract.
- Added a legacy-safe projection for generation records created before CX
  repair metadata persistence.

## Privacy And Ownership

- The projection contains hashes, status, counts, IDs, and bounded actions.
- Raw output, invalid output, prompt text, evidence text, provider details,
  and remediation handoff payloads are excluded.
- The projection declares owner-scope enforcement; the authenticated route is
  added separately in Slice 1055.
- No database, migration, or provider call is required.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_citation_quality_workflow.py \
  --test tests/test_nex_ae_chat.py \
  --coverage-target services/nex-ae-api/nex_ae_api/citation_quality_workflow.py
```

## Observed Evidence

- Slice Gate: pass (`2372 passed`, `2` separately protected PostgreSQL smoke
  tests skipped).
- Statement coverage: `97.91%` (threshold `95%`).
- Branch coverage: `95.80%` (threshold `94%`).
- `citation_quality_workflow.py`: statement `100%`, branch `100%`.
- Contract validation: pass (`100` schemas, `156` positive examples, `119`
  negative examples, `7` OpenAPI documents).
