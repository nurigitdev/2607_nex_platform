# Slice 0956: CX Owner-Scoped Summary Similarity

## Goal

Search document-summary vectors by cosine similarity without admitting stale,
cross-owner, inactive, or profile-incompatible payloads.

## Implementation

- Adds a PostgreSQL summary-similarity adapter over `cx_summary_vectors`.
- Applies exact tenant and owner filters before distance computation.
- Requires ACTIVE content, the latest READY document summary, READY embedding
  metadata, and exact summary hash, provider/model/deployment, vector digest,
  dimension, and profile-fingerprint agreement.
- Uses the 2560-dimension half-vector HNSW expression for the canonical
  `Qwen3-Embedding-4B` profile and generic pgvector cosine distance for bounded
  non-canonical test profiles.
- Supports a bounded result limit, minimum cosine score, and optional source
  document exclusion.
- Returns document/summary lineage, safe file metadata, hashes, rank, and score;
  raw vectors and cross-owner information are never projected.
- Fails closed on malformed database rows and redacts SQL/provider details from
  availability errors.
- Reconciles the S96 boundary audit so historical gaps are reported as either
  resolved by their planned implementation or still open. Six of seven gaps
  are resolved; document-intelligence observability remains open for Slice
  0958.

This Slice uses deterministic session doubles. Actual PostgreSQL and remote
embedding execution remain assigned to Slice 0959.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_summary_similarity.py \
  tests/test_cx_summary_similarity_adapter.py \
  --cov=nex_cx.summary_similarity \
  --cov=run_cx_summary_similarity_adapter \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_summary_similarity_adapter.py --summary
```

Observed on 2026-09-22:

- Focused boundary and summary-similarity suite: `45 passed`.
- Deterministic owner/freshness evidence: `10/10` checks passed.
- Boundary audit: `8` foundations, `7` historical gaps, `1` open gap, and
  `0` issues.
- Full regression: `7285 passed`.
- Statement coverage: `98.89%` (threshold `95%`).
- Branch coverage: `96.59%` (threshold `85%`).
- Contract validation: `85` schemas, `136` examples, `101` negative examples,
  and `7` OpenAPI documents passed.
