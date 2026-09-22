# Slice 0944: CX Fresh Vector Candidate Adapter

## Goal

Promote the S94 owner/freshness retrieval guard into a bounded vector candidate
adapter for permission-first S95 hybrid retrieval.

## Implementation

- Requires every vector target to carry a current
  `cx.private_owner_active.v1` visible permission decision before index access.
- Delegates exact tenant/owner lookup, source/profile/payload freshness, and
  pgvector search to the S94 `search_fresh_vector_index` guard.
- Excludes missing, owner-hidden, BUILDING, and stale indexes with aggregate
  reason counts so BM25-only fallback remains possible without exposing index
  identity.
- Cross-checks vector-index, content-object, and source chunk lineage before a
  match can become a candidate. Malformed or unexpected store responses fail
  closed with a redacted error.
- Globally sorts fresh matches by cosine score, deterministically deduplicates
  chunk candidates, applies a bounded limit, and returns metadata only. Raw
  embeddings and private chunk text are never included.
- Reuses the existing `cx_vector_indexes` and `cx_vectors` storage; no database
  migration or new table is required.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_vector_candidates.py \
  tests/test_cx_fresh_vector_candidate_contract.py \
  --cov=nex_cx.vector_candidates \
  --cov=run_cx_fresh_vector_candidate_contract \
  --cov-branch --cov-report=term-missing
```

Observed on 2026-09-22:

- Focused adapter/contract suite: `35 passed`; new adapter and contract runner
  statement/branch coverage `100%`.
- Deterministic contract: `PASS`, checks `8/8`; one fresh owner index admitted,
  one BUILDING index and one owner-hidden index excluded without disclosing
  their identities.
- Full quality gate: `6927 passed`; statement coverage `98.86%`; branch
  coverage `96.50%` (up from `96.49%`).
- Contract validation: schemas `85`, examples `136`, negative cases `101`,
  OpenAPI documents `7`.
- PostgreSQL and remote providers were not invoked in this Slice. S94 already
  proves the reused pgvector freshness guard against actual `nex_cx_test`;
  Slice 0949 will exercise the complete permission-filtered hybrid path against
  actual PostgreSQL plus remote embedding/reranking providers.
