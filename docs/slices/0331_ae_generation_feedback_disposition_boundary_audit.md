# Slice 0331: AE Generation Feedback/Disposition Boundary Audit

## Scope

Start S34 by freezing the boundary between user-facing generation feedback,
CX-owned generation lineage, and AG-owned operator disposition.

This slice does not add a runtime route yet. It records the safe storage policy
that the next AE feedback intake slices must follow.

## Implemented

- Added `ae_generation_feedback_boundary_decision.v1` as a small AE API decision
  module.
- Declared canonical owner services:
  - AE API owns user feedback intake;
  - CX owns generation lineage and grounded generation source records;
  - AG owns operator disposition and runbook workflow.
- Declared a feedback storage policy that permits IDs, hashes, short previews,
  reasons, and quality issue references while rejecting raw prompt, raw
  generation output, raw source text, and credential material.
- Added regression coverage for:
  - owner-service assignments;
  - raw-content policy;
  - sensitive-key detection in nested payloads.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_generation_feedback.py -q
```

Next slices:

```text
Slice 0332: AE generation feedback contract foundation
Slice 0333: AE feedback intake API + regression
Slice 0334: AE feedback PostgreSQL smoke evidence
```
