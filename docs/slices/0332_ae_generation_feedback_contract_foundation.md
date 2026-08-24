# Slice 0332: AE Generation Feedback Contract Foundation

## Scope

Freeze the first `ae_generation_feedback.v1` record shape before wiring an API
route or persistence adapter.

The contract keeps user feedback useful for later quality analytics while
avoiding raw prompt, raw generation output, source text, credential, and token
storage.

## Implemented

- Added `nex_ae_api.generation_feedback` with a deterministic feedback record
  builder.
- Normalized feedback values and reasons:
  - `positive`, `negative`, `neutral`;
  - `helpful`, `not_helpful`, `incorrect`, `citation_issue`, `irrelevant`,
    `incomplete`, `unsafe`, `slow`, `other`.
- Added comment handling that stores only:
  - `feedback_comment_hash`;
  - `feedback_comment_preview` capped at 240 characters.
- Added `quality_issue_refs` for safe references to AE/CX/AG quality issues.
- Added JSON Schema, positive fixture, negative raw-prompt fixture, and contract
  index entries.
- Expanded AE feedback regression coverage for schema validation and invalid
  payload branches.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_generation_feedback.py -q
18 passed
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=53 examples=85 negative_examples=62 openapi=7
```

Next slices:

```text
Slice 0333: AE feedback intake API + regression
Slice 0334: AE feedback PostgreSQL smoke evidence
```
