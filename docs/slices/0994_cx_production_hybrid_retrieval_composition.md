# Slice 0994: CX Production Hybrid Retrieval Composition

## Goal

Move the permission-hardened S95 hybrid retrieval composition out of protected
smoke code and into reusable CX service code.

## Implementation

- Added production candidate and evidence adapters behind a narrow
  `HybridRetrievalSource` protocol.
- Permission filtering now completes before query embedding, BM25, pgvector,
  private chunk loading, or reranking can execute.
- Query embeddings are requested through the NeX-MO capability alias and are
  validated as one bounded numeric vector.
- Candidate orchestration retains owner-scoped BM25, freshness-guarded vector
  retrieval, weighted RRF, and optional reranking.
- Evidence materialization rechecks the complete document scope before asking
  the source adapter for private chunk text.
- PostgreSQL/private-text source construction remains in Slice 0998 so this
  module contains no environment or global bootstrap coupling.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_hybrid_retrieval_runtime.py \
  --coverage-target services/nex-cx/nex_cx/hybrid_retrieval_runtime.py
```

## Observed Evidence

- Slice Gate: `2,152 passed`.
- Repository statement coverage: `99.00%`.
- Repository branch coverage: `98.05%`.
- Hybrid retrieval runtime statement/branch coverage: `100%`/`100%`.
- Contract validation: `91` schemas, `142` positive examples, `107` negative
  examples, and `7` OpenAPI documents.
- Boundary audit: resolved gaps `2/8`, next Slice `0995`.
