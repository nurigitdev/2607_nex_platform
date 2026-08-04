# Slice 0078: Weighted RRF hybrid retrieval

## Intent

Slice 0078 adds the first executable path for the planned
`weighted_rrf_vector_bm25_v1` retrieval policy.

The existing `retrieval_quality_v1` behavior remains available and unchanged:
BM25 score plus embedding index presence. The new weighted RRF path is opt-in
through the retrieval policy payload until Slice 0079 wires active policy
application.

## Runtime Behavior

- Policy id / ranker mix: `weighted_rrf_vector_bm25_v1`
- Default vector weight: `0.7`
- Default BM25 weight: `0.3`
- Default RRF `k`: `60`
- Default vector candidate limit: `80`
- Default BM25 candidate limit: `80`
- Query embedding input: optional `query_embedding` numeric list

When a query embedding is provided, CX ranks chunks independently by vector
cosine similarity and BM25, then combines the two ranks with weighted RRF.

When no query embedding is provided, CX safely degrades to BM25-only RRF. This
keeps mock-first tests and text-only retrieval available while preserving the
same policy shape.

Raw query embedding vectors are not exposed in retrieval packages. CX records
only a `query_embedding_snapshot` with `provided`, `vector_dimension`, and
`embedding_sha256`.

## Score Shape

Weighted RRF candidates include:

- `vector_score`
- `bm25_score`
- `rrf_score`
- `bm25_rank`
- `vector_rank`
- `hybrid_score`
- `final_score`

`rrf_score` is the raw weighted reciprocal-rank score. `final_score` is
normalized to `0.0..1.0` so existing confidence thresholds remain usable.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_cx_retrieval.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
