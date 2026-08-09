# Slice 0167: CX Chunk Embedding Persistence Adapter

## Scope

Slice 0167 adds PostgreSQL-ready persistence for CX chunk embedding metadata
behind the existing ingestion store and repository boundary.

Implemented:

- `build_chunk_embedding_index_record()` metadata mapper for public
  `cx_embedding_index.v1` records
- in-memory and SQLAlchemy repository support for `cx_chunk_embeddings`
- idempotent lookup keyed by `chunk_set_id + model_profile_id + model_revision`
- `ContentIngestionStore.save_embedding_index()` write-through to the
  repository when a persisted chunk set is available
- SQLite regression fixture coverage for chunk embedding DDL shape and unique
  keys
- audit refresh showing chunk embedding metadata as SQLAlchemy repository ready

## Persistence Boundary

The runtime embedding response remains `cx_embedding_index.v1`; no public route
response shape changed.

The database rows store only:

- persisted chunk lineage
- provider alias and model/deployment lineage
- vector dimension
- embedding hash
- optional embedding storage URI
- status and trace/timestamp metadata

Raw embedding vectors remain outside `cx_chunk_embeddings`. The current
mock-first runtime keeps vectors in `ContentIngestionStore.embedding_vectors`;
future pgvector or external vector storage can use `embedding_storage_uri`
without changing the public embedding index shape.

Because the current public embedding index has no separate `model_profile_id`,
the adapter uses `provider_alias` as the default model profile key unless a
future record supplies `model_profile_id` explicitly.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_embedding_index.py tests/test_nex_cx_persistence_audit.py tests/test_nex_cx_retrieval.py
```

Expected result:

```text
171 passed, 1 warning
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1319 passed, 1 warning
statement_coverage=98.24% threshold=95.00%
branch_coverage=94.16% threshold=85.00%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
```
