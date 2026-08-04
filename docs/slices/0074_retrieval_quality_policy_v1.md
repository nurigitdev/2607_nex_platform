# Slice 0074 Retrieval Quality Policy v1

Status: Implemented.

Backlog candidate: `S7-004` Retrieval quality policy v1.

Requirement coverage: `CX-FR-003`, `CX-FR-004`, `TRACE-CONTENT-001`,
`PLAT-FR-007`.

## Scope

Slice 0074 separates CX retrieval quality settings from hard-coded scoring
logic while preserving the current default behavior.

Canonical v1 defaults:

- Policy ID: `retrieval_quality_v1`
- Ranker mix: `bm25_with_embedding_presence`
- Reranked mix: `bm25_embedding_with_rerank`
- BM25 weight: `0.85`
- Embedding-presence weight: `0.15`
- Embedding-presence score: `0.5`
- Low-confidence threshold: `0.2`
- Rerank candidate limit: `50`
- Neighbor policy marker: `not_loaded_in_slice_0017`

Requests may provide a bounded `retrieval_policy` object to override numeric
quality knobs for regression tests, smoke evidence, and future tenant-level
policy experiments. Invalid policy values fail with
`cx.retrieval_policy_invalid`.

## Package Evidence

Retrieval context packages now include:

- `retrieval_profile.quality_policy`
- `score_summary.quality_policy_id`
- `score_summary.low_confidence_threshold`

The package hash also includes the quality policy snapshot so packages created
with different scoring policy values remain distinguishable.

## Reranking

Reranking now applies only to the first `rerank_candidate_limit` ranked
candidates. Remaining candidates are preserved in their prior rank order. This
keeps direct vLLM reranker calls bounded before live RAG smoke testing expands.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_cx_retrieval.py
scripts/quality/run_quality_gate.sh
```
