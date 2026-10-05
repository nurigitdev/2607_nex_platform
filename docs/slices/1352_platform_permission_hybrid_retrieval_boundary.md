# Slice 1352: Platform Permission Hybrid Retrieval Boundary

## Goal

Freeze the S136 live permission-filtered hybrid retrieval boundary before
changing runtime or acceptance behavior.

## Decision

- Reuse the production CX runtime delivered by S95/S100 and the index-ready
  owner-scoped document delivered by S135.
- Require actual `nex_cx_test`, Qwen3-Embedding-4B, and
  Qwen3-Reranker-4B evidence for closure. The generation provider is outside
  S136.
- Keep permission admission before every candidate and private-payload access.
- Preserve BM25 `1.2/0.75`, weighted RRF `0.7/0.3`, `rrf_k=60`, and confidence
  threshold `0.2` until calibration evidence justifies a versioned policy.
- Use Slice Gate on every Slice, Checkpoint Gate at 1356, and Full Gate at
  1361.

No database table, migration, route, or provider payload shape changes in this
Slice.

## Baseline Evidence

The existing protected S95 smoke was rerun against the actual test database
and current live providers before implementation: `16/16` checks passed with
live embedding and live reranking, including cleanup.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_platform_permission_hybrid_retrieval_boundary.py \
  --coverage-target scripts/smoke/run_platform_permission_hybrid_retrieval_boundary.py \
  --smoke scripts/smoke/run_platform_permission_hybrid_retrieval_boundary.py
```
