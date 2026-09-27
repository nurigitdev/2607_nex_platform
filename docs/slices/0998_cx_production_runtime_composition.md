# Slice 0998: CX Production Runtime Composition

## Goal

Replace the manually assembled S95/S100 smoke dependencies with one PostgreSQL
runtime composition used by the CX service bootstrap.

## Implementation

- Added an owner-scoped PostgreSQL retrieval source for content metadata, the
  latest READY vector manifest, and private chunk evidence.
- Revalidates ACTIVE owner scope in SQL before loading private text, then relies
  on the immutable private-text store to verify each chunk SHA-256.
- Composes PostgreSQL BM25, freshness-guarded pgvector search, NeX-MO embedding,
  optional reranking, and authorized evidence materialization behind the
  hardened retrieval runtime.
- Replaces the durable ingestion embedding checkpoint with the S100 vector
  indexer, preserving the remaining checkpoint handlers.
- Uses separate API and worker pgvector stores so retrieval and vector publish
  retain their configured connection-pool workloads.
- Wires the hardened runtime into the canonical retrieval route in PostgreSQL
  mode and exposes the ingestion handlers through application state for the
  worker process boundary.
- Adds no database table or migration and exposes no database URL or private
  payload in runtime summaries.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_mvp_runtime.py \
  --coverage-target services/nex-cx/nex_cx/mvp_runtime.py \
  --coverage-target services/nex-cx/nex_cx/main.py
```

## Observed Evidence

- Slice Gate: `2,225 passed`.
- Repository statement coverage: `99.03%`.
- Repository branch coverage: `98.12%`.
- New runtime statement/branch coverage: `100%`/`100%`.
- CX bootstrap statement/branch coverage: `99.18%`/`95.00%`.
- Contract validation: `91` schemas, `142` positive examples, `107` negative
  examples, and `7` OpenAPI documents.
- Boundary audit: resolved gaps `6/8`, next Slice `0999`.
