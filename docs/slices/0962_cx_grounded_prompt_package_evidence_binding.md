# Slice 0962: CX Grounded Prompt Package Evidence Binding

## Goal

Build the generation-provider prompt in CX from the exact owner-admitted
retrieval package and selected evidence instead of forwarding the AE prompt
without grounded context.

## Implementation

- Added a deterministic `cx_grounded_prompt_package.v1` builder.
- The prompt uses a fixed system instruction followed by a canonical JSON
  envelope containing the user question and citation-labelled evidence.
- Question and evidence values are explicitly treated as untrusted data;
  instructions embedded in either value cannot replace the system policy.
- Explicit evidence selection is validated against the retrieval package and
  materialized in retrieval-rank order. An omitted selection binds every
  admitted evidence item.
- Package, query, evidence content, and evidence binding hashes provide stable
  lineage without copying private text into provider metadata.
- Grounded generation now sends the canonical messages to NeX-MO and rejects
  malformed evidence before any provider call. General generation behavior is
  unchanged.

## Limits

- A prompt package accepts at most 20 evidence items.
- A query is limited to 16,000 characters and each evidence text to 20,000
  characters.
- Durable private generated-output storage, provider-output normalization, and
  SQL execution persistence remain assigned to Slices 0963-0965.
- PostgreSQL and DGX are not required for this deterministic Slice.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_grounded_prompt.py \
  tests/test_nex_cx_generation.py \
  tests/test_cx_grounded_generation_runtime_boundary_audit.py \
  --cov=nex_cx.grounded_prompt --cov=nex_cx.generation \
  --cov=run_cx_grounded_generation_runtime_boundary_audit \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_grounded_generation_runtime_boundary_audit.py \
  --summary
```

PostgreSQL and DGX are intentionally not invoked in this Slice.

Observed result:

- focused prompt/generation/audit regression: `77 passed`
- prompt package module coverage: statement `100%`, branch `100%`
- related generation/draft/progress/live-shape regression: `118 passed`
- the first full run exposed five stale fixtures that omitted evidence text or
  assumed a user-only provider message; the fixtures were hardened and all five
  failures passed independently before the full rerun
- S97 boundary summary: `PASS`, gaps `8`, open `7`, issues `0`
- final full regression: `7,362 passed`
- full statement coverage: `98.90%`
- full branch coverage: `96.60%`
- contract validation: `87` schemas, `138` examples, `103` negative
  examples, and `7` OpenAPI documents
- quality gate exit status: `0`
