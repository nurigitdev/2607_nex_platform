# Slice 0161: CX Persistence Gap Audit and Refactoring Checkpoint

## Scope

Slice 0161 starts the CX-focused persistence workstream with a refactoring
checkpoint instead of a database adapter jump.

Implemented:

- `cx_persistence_gap_audit.v1` checkpoint builder for the current CX ingestion
  store
- normalized `memory` and `postgres` audit modes
- redaction-safe observed counts for current in-memory CX surfaces
- explicit mapping from CX runtime surfaces to existing migration tables
- private payload boundary inventory for source bytes, extracted text, chunk
  text, embeddings, summaries, and summary embeddings
- regression coverage that proves audit output does not expose seeded private
  source, chunk, or summary payload text

## Persistence Findings

The audit separates the current CX state into three categories:

| Category | Status |
| --- | --- |
| Source files and content objects | Repository port exists; PostgreSQL adapter still missing. |
| Extraction, chunks, lexical index, embeddings, summaries, retrieval packages, processing runs | Runtime remains `ContentIngestionStore` memory-only. |
| Raw/private payloads | Must remain outside public operational projections and be represented by hashes, dimensions, sizes, offsets, or storage URIs only. |

Existing migrations already provide the main CX target tables for source files,
content objects, extraction artifacts, chunks, embeddings, lexical postings,
summaries, and summary embeddings. Retrieval package and processing run
persistence remains schema-deferred until the runtime contract is narrowed.

## Refactoring Checkpoint

Do not add route-level PostgreSQL writes directly to each CX endpoint.

The next implementation should introduce a service-local SQLAlchemy content
ingestion repository behind the current store boundary, keeping:

- source file metadata separate from raw local/object-storage bytes
- tenant/user-owned content objects separate from global file hashes
- private text/vector payloads out of AG/debug projections
- SQLite regression coverage aligned with PostgreSQL smoke coverage
- extraction, chunking, embedding, summary, retrieval, and generation routes
  insulated from storage-specific branches

Recommended next slice:

```text
Slice 0162: SQLAlchemy CX content ingestion repository foundation
```

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
4 passed
```
