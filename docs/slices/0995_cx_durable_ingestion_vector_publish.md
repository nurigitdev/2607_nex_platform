# Slice 0995: CX Durable Ingestion Vector Publish

## Goal

Connect the durable ingestion embedding checkpoint to owner-private chunk-text
storage and the S94 freshness-guarded pgvector publish path.

## Implementation

- Added an injectable MVP ingestion indexing handler for the existing durable
  checkpoint coordinator; the legacy embedding handler remains the default.
- Persists each chunk as immutable owner-scoped private text and validates its
  public SHA-256 metadata before any provider request.
- Requests chunk embeddings through a NeX-MO capability alias, validates count,
  numeric shape, and consistent dimensions, then builds the canonical source
  snapshot and embedding profile.
- Atomically publishes all vectors through the existing vector manifest and
  pgvector adapter, returning a metadata-only `cx.vector_index:<id>` checkpoint.
- Replays reuse an existing compatible READY vector index and reject non-ready
  identity conflicts for explicit recovery.
- Adds no database table or migration.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_mvp_ingestion_indexing.py \
  --coverage-target services/nex-cx/nex_cx/mvp_ingestion_indexing.py
```

## Observed Evidence

- Slice Gate: `2,165 passed`.
- Repository statement coverage: `99.00%`.
- Repository branch coverage: `98.06%`.
- New indexer and changed coordinator statement/branch coverage:
  `100%`/`100%` each.
- Contract validation: `91` schemas, `142` positive examples, `107` negative
  examples, and `7` OpenAPI documents.
- Boundary audit: resolved gaps `3/8`, next Slice `0996`.
