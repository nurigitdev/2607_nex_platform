# Slice 0946: CX Weighted RRF and Rerank Privacy Hardening

## Goal

Fuse only Slice 0945 permission-admitted lexical and vector candidates with the
canonical weighted RRF policy, then ensure reranking receives only owner-scoped
private chunk text whose identity and digest match the admitted candidates.

## Implementation

- Revalidates the candidate-set schema, permission policy, actor, tenant,
  visible document scope, and query SHA-256 before ranking.
- Validates and deterministically orders each candidate channel, rejects
  foreign, duplicate, malformed, or conflicting chunk lineage, and strips
  candidate previews from ranking output.
- Applies the canonical `weighted_rrf_vector_bm25_v1` policy with vector weight
  `0.7`, BM25 weight `0.3`, `k=60`, and rerank candidate limit `50`.
- Uses an explicit owner-scoped text-loader port only when reranking is
  requested. Loaded rows must exactly match the bounded rerank window by
  `(content_object_id, chunk_id)` and their SHA-256 digest.
- Requires a complete, unique, bounded reranker result permutation. Invalid or
  partial provider output fails closed; dependency failures return redacted,
  retryable errors.
- Returns scores, ranks, hashes, permission evidence, and safe provider
  metadata without returning query text or private chunk text.
- Keeps the legacy retrieval path intact until Slice 0947 wires this hardened
  result into the retrieval package API and persistence boundary.
- Adds no table, migration, route, persistent row, or external provider call.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_hybrid_ranking.py \
  tests/test_cx_weighted_rrf_rerank_privacy_contract.py \
  --cov=nex_cx.hybrid_ranking \
  --cov=run_cx_weighted_rrf_rerank_privacy_contract \
  --cov-branch --cov-report=term-missing
```

Focused results:

- `91 passed`.
- Ranking module statement/branch coverage: 100%/100%.
- Contract runner statement/branch coverage: 100%/100%.
- Deterministic contract evidence: `10/10` checks passed.

Full quality-gate results:

- `7059 passed`.
- Repository statement coverage: 98.87%.
- Repository branch coverage: 96.53%.
- Contract validation: 85 JSON Schemas, 136 examples, 101 negative examples,
  and 7 OpenAPI documents passed.

PostgreSQL and remote reranker access were intentionally not invoked and remain
deferred to the protected Slice 0949 smoke.
