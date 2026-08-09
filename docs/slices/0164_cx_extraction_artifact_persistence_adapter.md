# Slice 0164: CX Extraction Artifact Persistence Adapter

## Scope

Slice 0164 adds PostgreSQL-ready persistence for CX extraction artifacts behind
the existing ingestion store and repository boundary.

Implemented:

- `build_extraction_artifact_record()` metadata mapper for extraction results
- `markdown_storage_uri_from_path()` local Markdown URI mapper
- in-memory and SQLAlchemy repository support for `cx_extraction_artifacts`
- `ContentIngestionStore.save_extraction_result()` write-through to the
  repository when content/source refs are available
- idempotent lookup keyed by
  `content_object_id + extractor_name + extractor_version + markdown_sha256`
- SQLite regression fixture for `cx_extraction_artifacts`
- audit refresh showing source files, content objects, and extraction artifacts
  as SQLAlchemy repository ready

## Persistence Boundary

The runtime extraction result response remains `cx_text_extraction.v1`; no new
public response field was added.

The database row stores only:

- content/source lineage
- extractor name and version
- Markdown hash
- Markdown storage URI
- character count
- trace/timestamp metadata

The raw Markdown body and original source payload remain outside the database.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_ingestion.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
105 passed
```
