# Slice 0169: CX Summary Embedding Persistence Adapter

## Scope

Slice 0169 adds PostgreSQL-ready persistence for CX document summary embedding
metadata behind the existing ingestion store and repository boundary.

Implemented:

- `build_summary_embedding_persistence_record()` mapper for public
  `cx_document_summary_embedding.v1` records
- in-memory and SQLAlchemy repository support for
  `cx_document_summary_embeddings`
- idempotent lookup keyed by
  `document_summary_id + model_profile_id + model_revision`
- `ContentIngestionStore.save_summary_embedding_index()` write-through when a
  persisted document summary is available
- SQLite regression fixture coverage for summary embedding DDL shape and unique
  key behavior
- audit refresh showing summary embedding metadata as SQLAlchemy repository
  ready

## Persistence Boundary

The runtime summary embedding response remains
`cx_document_summary_embedding.v1`; no public route response shape changed.

The database rows store only:

- persisted document summary lineage
- provider alias and model/deployment lineage
- vector dimension
- embedding hash
- optional embedding storage URI
- status and trace/timestamp metadata

Raw summary embedding vectors remain outside
`cx_document_summary_embeddings`. The current mock-first runtime keeps them in
`ContentIngestionStore.summary_embedding_vectors`; future pgvector or external
vector storage can use `embedding_storage_uri` without changing the public
summary embedding shape.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_summary_embeddings.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
104 passed, 1 warning
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1341 passed, 1 warning
statement_coverage=98.26% threshold=95.00%
branch_coverage=94.20% threshold=85.00%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
```
