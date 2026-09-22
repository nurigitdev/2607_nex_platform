# Slice 0954: CX Document Summary Generation Provider Adapter

## Goal

Introduce a fail-closed document-summary adapter over the existing NeX-MO
generation port while retaining the deterministic local summary path as the
default regression composition.

## Implementation

- Builds a `general-llm-default` MO request with the prompt-registry system
  prompt and extracted Markdown as separate system/user messages.
- Uses the current `Qwen3.5-4B` model profile, deterministic
  temperature, non-streaming batch workload, 512 output tokens, and the
  60-second generation timeout profile.
- Keeps raw Markdown inside the provider request only. Request metadata carries
  the source SHA-256, model profile, purpose, and 900/1000 character policy.
- Validates text output, non-empty content, completion reason, model revision,
  deployment, provider type, generation ID, and safe usage metadata.
- Rejects truncated or greater-than-1000-character responses as retryable
  upstream failures rather than silently accepting incomplete summaries.
- `build_and_store_document_summary` accepts an optional MO client. Provider
  lineage is recorded in summary metadata, while the no-client path retains
  the established local deterministic summary behavior.
- Prompt render events retain the final output hash for both local and
  provider-backed summaries.

This Slice uses a deterministic fake MO client. PostgreSQL and the DGX live
generation endpoint remain deferred to Slice 0959.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_document_summary_generation.py \
  tests/test_nex_cx_summaries.py \
  --cov=nex_cx.document_summary_generation \
  --cov=run_cx_document_summary_generation_adapter \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_document_summary_generation_adapter.py --summary
```

Observed on 2026-09-22:

- Focused generation-adapter suite: 39 passed; adapter and evidence runner
  statement/branch coverage 100%.
- Deterministic adapter evidence: 10/10 checks passed.
- Full regression: 7,210 passed; quality gate exit 0.
- Full coverage: 98.89% statements and 96.57% branches.
- Contract validation: 85 JSON Schema files, 136 examples, 101 OpenAPI
  examples, and 7 OpenAPI documents passed.
