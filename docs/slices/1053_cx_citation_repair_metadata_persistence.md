# Slice 1053: CX Citation Repair Metadata Persistence

## Goal

Preserve the privacy-safe bounded citation repair outcome in the durable CX
generation record and owner-scoped read model so AE can build an explainable
workflow projection.

## Implementation

- Added strict validation for `cx_citation_repair.v1` projections.
- Persisted the async worker repair projection under generation
  `request_metadata.citation_repair`.
- Added the nested repair projection to the CX read-model allowlist.
- Rejected inconsistent attempts, triggers, hashes, package reuse, extra
  fields, and invalid-output inclusion.
- Kept synchronous generation callers backward compatible with an optional
  repair projection.

## Decisions

- The durable projection contains only attempt state, bounded counts, trigger
  code, prompt-package hashes, same-package confirmation, and redaction flags.
- Invalid provider output, prompt text, evidence text, and provider details are
  not persisted.
- No table, migration, provider call, or PostgreSQL access is required.
- Generation records omit `citation_repair` when no bounded repair was
  evaluated, preserving the existing synchronous record shape.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_citation_repair.py \
  --test tests/test_nex_cx_async_generation_worker.py \
  --test tests/test_nex_cx_generation_read_model.py \
  --coverage-target services/nex-cx/nex_cx/citation_repair.py \
  --coverage-target services/nex-cx/nex_cx/generation_read_model.py
```

## Observed Evidence

- Slice Gate: pass (`2253 passed`).
- Statement coverage: `99.04%` (threshold `95%`).
- Branch coverage: `98.14%` (threshold `94%`).
- Target coverage:
  - `citation_repair.py`: statement `100%`, branch `100%`.
  - `generation_read_model.py`: statement `100%`, branch `100%`.
- Contract validation: pass (`100` schemas, `156` positive examples, `119`
  negative examples, `7` OpenAPI documents).
