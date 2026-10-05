# Slice 1356: CX Weighted RRF Acceptance

## Goal

Expose enough privacy-safe channel evidence to prove weighted RRF behavior
without replaying private candidates or text.

## Implementation

- Added a candidate summary under the retrieval profile with BM25, vector,
  fused, both-channel, BM25-only, and vector-only counts.
- Preserved the versioned `weighted_rrf_vector_bm25_v1` policy with vector
  weight `0.7`, BM25 weight `0.3`, and `rrf_k=60`.
- Kept per-evidence BM25/vector ranks, channel scores, normalized RRF score,
  rerank score, and final score for authorized evidence only.
- Candidate summaries contain counts only; document IDs, chunk IDs, terms,
  query text, vectors, and private text are not duplicated into operations
  evidence.

No table, migration, or route was added.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_cx_weighted_rrf_acceptance.py \
  --coverage-target services/nex-cx/nex_cx/hybrid_retrieval_package.py \
  --coverage-target scripts/smoke/run_cx_weighted_rrf_acceptance.py \
  --smoke scripts/smoke/run_cx_weighted_rrf_acceptance.py

scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_cx_weighted_rrf_acceptance.py \
  --coverage-target services/nex-cx/nex_cx/hybrid_retrieval_package.py \
  --coverage-target scripts/smoke/run_cx_weighted_rrf_acceptance.py \
  --smoke scripts/smoke/run_cx_weighted_rrf_acceptance.py
```

Observed results:

- focused acceptance: `54 passed`, changed targets at 100% statement and
  branch coverage
- Slice Gate: `2334 passed`, statement coverage `99.08%`, branch coverage
  `98.17%`
- Checkpoint Gate: `PASS` in `654.64s`, statement coverage `98.91%`, branch
  coverage `97.28%`
