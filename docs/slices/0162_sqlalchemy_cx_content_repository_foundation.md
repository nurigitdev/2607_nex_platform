# Slice 0162: SQLAlchemy CX Content Repository Foundation

## Scope

Slice 0162 implements the first CX persistence adapter behind the existing
`CxContentRepository` port.

Implemented:

- `SqlAlchemyCxContentRepository` for `cx_source_files`,
  `cx_content_objects`, and `cx_content_acl_entries`
- idempotent source file persistence keyed by `source_sha256`
- active owner/content lookup keyed by `tenant_id + owner_user_id + source_sha256`
- owner ACL row creation when a content object is persisted
- checksum verification timestamp update for materialized local source files
- SQLite regression fixture aligned with the PostgreSQL migration shape
- repository error wrapping for missing tables or unavailable database state

## Design Notes

The adapter deliberately stays behind the current repository boundary.

Routes and ingestion pipeline code should continue to call
`ContentIngestionStore` and `CxContentRepository`; PostgreSQL-specific behavior
must stay inside the adapter. This keeps upload, extraction, chunking,
embedding, summary, retrieval, and generation routes from accumulating
storage-specific branches.

The source file table stores metadata and local/object-storage links only.
Raw source bytes, extracted text, chunk text, summaries, and vectors remain
outside this repository surface.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
15 passed
```
