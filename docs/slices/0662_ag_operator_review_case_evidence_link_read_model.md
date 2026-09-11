# Slice 0662: AG operator review case evidence-link read model

## Intent

Add the first S67 runtime read model for case-scoped evidence links without
introducing a new evidence-link table.

## Scope

- Add `ag_operator_review_case_evidence_links.v1` as the case evidence-link
  projection version.
- Add `OperatorReviewCaseService.get_case_evidence_links(...)` for target-scoped
  note/export retrieval.
- Add `build_operator_review_case_evidence_links_projection(...)` for a
  metadata-safe mixed evidence list.
- Reuse existing AG-owned data sources:
  - `ag_op_cases`
  - `ag_op_notes`
  - `ag_ev_exports`
- Keep route wiring deferred to Slice 0663.

## Projection Contract

The projection returns only safe refs, hashes, bounded previews, counts, status
fields, timestamps, and detail paths:

- operator review notes expose `operator_note_hash` and
  `operator_note_preview`, not the raw note.
- redacted evidence exports expose `evidence_hash`, `evidence_item_count`, and
  `redaction_profile`, not `evidence_manifest` or raw evidence bodies.
- case source, timeline, and future action-admission links are returned as
  route refs only.

## Privacy Guard

The read model excludes raw notes, evidence bodies, case/action comments,
prompts, source text, storage paths, provider payloads, database URLs, tokens,
idempotency keys, and raw metadata payloads.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

The targeted case test suite covers matching, non-matching, empty-source,
limit, missing-id, and service-store filter paths for the evidence-link read
model.
