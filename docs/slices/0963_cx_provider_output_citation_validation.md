# Slice 0963: CX Provider Output and Citation Validation

## Goal

Fail closed on malformed, incomplete, empty, or incorrectly cited generation
provider output before CX creates a successful structured draft.

## Implementation

- Added `cx_grounded_output_validation.v1` normalization for every NeX-MO
  generation response.
- Required provider lineage fields, text output, non-empty content, and a
  terminal `STOP` finish reason are validated before the response enters CX.
- Usage is restricted to non-negative integer token counts and runtime metadata
  is copied before later public-record sanitization.
- Grounded output must contain citations and every citation must resolve to the
  exact owner-admitted selected evidence set. Unknown or unselected citations
  are rejected.
- Provider validation failures use the existing failed execution/progress path
  and are never reported as completed generations.
- Validation audit metadata contains only hashes, counts, and citation labels;
  raw generated text is excluded.

## Decision

- A grounded answer must cite at least one admitted evidence item, but it need
  not cite every selected item when the answer does not use every item.
- Any non-`STOP` finish reason is incomplete and retryable for this bounded text
  generation contract.
- Automatic citation repair remains deferred; S97 records a failed attempt and
  lets the existing recovery policy decide whether to retry.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_grounded_output_validation.py \
  tests/test_nex_cx_generation.py \
  tests/test_nex_cx_drafts.py \
  tests/test_nex_cx_progress.py \
  tests/test_cx_grounded_generation_runtime_boundary_audit.py \
  --cov=nex_cx.grounded_output_validation --cov=nex_cx.generation \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_grounded_generation_runtime_boundary_audit.py \
  --summary
```

PostgreSQL and DGX are intentionally not invoked in this deterministic Slice.

Observed result:

- focused output-validation/generation/draft/progress regression: `98 passed`
- output validator coverage: statement `100%`, branch `100%`
- protected live request-shape regression: `23 passed`
- expanded CX/MO/traceable-flow regression: `165 passed`
- the first full run exposed an uncited mock-provider response in the traceable
  flow; the mock provider now parses the grounded envelope and cites its first
  admitted label deterministically
- malformed grounded-envelope branch regression: `11` additional cases
- S97 boundary summary: `PASS`, gaps `8`, open `6`, issues `0`
- final full regression: `7,405 passed`
- full statement coverage: `98.90%`
- full branch coverage: `96.60%`
- contract validation: `87` schemas, `138` examples, `103` negative
  examples, and `7` OpenAPI documents
- quality gate exit status: `0`
