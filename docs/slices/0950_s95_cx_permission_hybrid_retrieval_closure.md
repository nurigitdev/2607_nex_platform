# Slice 0950: S95 CX Permission Hybrid Retrieval Closure

## Closure Result

S95 closes as `READY_FOR_S96` with
`CX_PERMISSION_FILTERED_HYBRID_RETRIEVAL_READY` readiness.

- `cx.private_owner_active.v1` is the fail-closed MVP permission policy.
  Cross-owner, inactive, missing, and malformed content is indistinguishable
  from not found before candidate generation.
- Owner-scoped PostgreSQL BM25 uses `k1=1.2` and `b=0.75`; vector candidates
  require an owner-admitted, source/profile/payload-compatible READY pgvector
  index.
- Permission admission precedes tokenization, BM25 access, vector retrieval,
  private text loading, weighted RRF, and reranking.
- Fusion uses vector/BM25 weights `0.7/0.3` with `rrf_k=60`. Reranking receives
  only digest-verified private text for authorized candidates.
- The current live profiles are `Qwen3-Embedding-4B` at 2560 dimensions and
  `Qwen3-Reranker-4B`. The 0.6B reranker remains only in the explicit NeX-PCX
  legacy compatibility profile.
- Canonical retrieval packages persist private owner query/evidence hashes with
  `NULL` previews under `hash_only_private_owner`.
- Success and failure observability is metadata-only and best-effort, so an
  event-store failure cannot change the primary retrieval result.

## Actual Evidence

The Slice 0943 smoke completed 9 checks against the actual
`nex_cx_user@nex_cx_test` database and proved owner-scoped BM25 ordering while
excluding foreign and inactive content.

The Slice 0949 protected smoke completed all 16 checks through the canonical
API using the actual PostgreSQL database, live DGX embedding, fresh pgvector
retrieval, weighted RRF, and live `Qwen3-Reranker-4B`. It verified HTTP 200,
hash-only persistence, absence of private payloads in evidence, and complete
fixture cleanup.

## Scope Boundary

This closure claims an owner-private permission-filtered hybrid retrieval
runtime, not a general ACL or production-scale search platform. The following
remain deferred:

- shared document, group, and ACL expansion after OA defines canonical claims;
- multi-document ANN/BM25 scale and performance validation;
- production provider latency, capacity, and availability SLO baselines.

PostgreSQL/pgvector remains the production retrieval backend, and the
versioned SQL plus `schema_migrations` runner remains the sole migration
history.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s95_cx_permission_hybrid_retrieval_closure.py \
  --cov=run_s95_cx_permission_hybrid_retrieval_closure \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_s95_cx_permission_hybrid_retrieval_closure.py --summary
```

The closure is deterministic and performs no database or provider call. It
requires the separately protected Slice 0949 live evidence before it can pass.

Observed on 2026-09-22:

- Focused closure suite: `7 passed`.
- Closure runner statement/branch coverage: 100%/100%.
- Closure evidence: `PASS`, deterministic evidence `7/7`, contract checks
  `55`, PostgreSQL checks `25`, protected live checks `16`, next requirement
  `S96`.
- Full regression: `7144 passed`, statement coverage `98.88%`, branch coverage
  `96.56%`.
- Contract validation: 85 JSON Schemas, 136 examples, 101 negative examples,
  and 7 OpenAPI documents passed.
- Full quality gate and the final S95 closure check completed with exit code
  `0`.
