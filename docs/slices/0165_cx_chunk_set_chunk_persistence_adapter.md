# Slice 0165: CX Chunk Set/Chunk Persistence Adapter

## Scope

Slice 0165 adds PostgreSQL-ready persistence for CX chunk set and chunk
metadata behind the existing ingestion store and repository boundary.

Implemented:

- `build_chunk_set_record()` metadata mapper for public `cx_chunk_set.v1`
  records
- in-memory and SQLAlchemy repository support for `cx_chunk_sets` and
  `cx_chunks`
- idempotent lookup keyed by
  `content_object_id + extraction_artifact_id + chunk_policy_id +
  source_markdown_sha256`
- `ContentIngestionStore.save_chunk_set()` write-through to the repository when
  content refs and matching extraction artifacts are available
- SQLite regression fixture coverage for chunk set/chunk DDL shape and unique
  keys
- audit refresh showing source files, content objects, extraction artifacts, and
  chunks as SQLAlchemy repository ready

## Persistence Boundary

The runtime chunk response remains `cx_chunk_set.v1`; no public route response
shape changed.

The database rows store only:

- content and extraction artifact lineage
- chunk policy, size, and overlap
- source Markdown hash
- chunk ordinal, offsets, character counts, text hashes, and short previews
- trace/timestamp metadata

Full chunk text remains outside the public metadata tables. The current
mock-first runtime keeps it in `ContentIngestionStore.chunk_texts`; a future
private chunk text store or Markdown-offset reconstruction path can replace that
boundary without changing `cx_chunk_sets` or `cx_chunks`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_chunking.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
67 passed
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1300 passed
statement_coverage=98.22%
branch_coverage=94.10%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
```
