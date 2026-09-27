# Slice 1027: AE Generation Policy Package

## Goal

Compose the exact AE intent, template, prompt, output, quality, ownership, and
retrieval decisions into one deterministic package for the CX handoff.

## Implementation

- Add a pure generation-policy package composer with a deterministic package
  hash and resolved-policy hash lineage.
- Bind the active prompt binding/version and content hash without copying
  prompt content.
- Bind tenant/user ownership and retrieval package/evidence IDs without raw
  evidence text.
- Require an admitted retrieval package for grounded policies and reject one
  for general-answer policies.
- Reject provider runtime fields, raw prompt-bearing policy records, mismatched
  prompt versions, invalid hashes, and evidence selections outside the package.

## Decisions

- The policy package is metadata-only; the user message remains a separate CX
  request field and is represented here only by SHA-256.
- CX remains responsible for provider-facing prompt construction.
- Chat route integration follows in Slice 1028; no database or provider call is
  required in this Slice.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_generation_policy.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generation_policy.py \
  --smoke scripts/smoke/run_ae_generation_policy_package.py
```

## Observed Evidence

- Slice Gate: `2,067 passed` with one known dependency warning.
- Repository statement coverage: `97.87%`.
- Repository branch coverage: `95.66%`.
- Generation-policy composer statement/branch coverage: `100%`/`97.83%`.
- Contract validation: `93` schemas, `147` examples, `110` negative
  examples, and `7` OpenAPI documents.
- Generation-policy package smoke: `11/11`, next Slice `1028`.
