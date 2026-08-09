# Slice 0182: CX Processing Run/Step Schema Migration

## Scope

Slice 0182 adds the PostgreSQL schema for durable CX document processing run and
step metadata.

Implemented:

- `database/nex-cx/migrations/0182_cx_processing_run_step_persistence.sql`
- `cx_document_processing_runs`
- `cx_document_processing_steps`
- schema regression coverage in `tests/test_database_schema_foundation.py`
- CX persistence audit status update to
  `schema_migration_present_adapter_pending`

## Decision

Processing runs are persisted as operational metadata records, not raw document,
prompt, extraction, chunk, summary, or vector storage.

The run table stores pipeline identity, document identity, trace/request IDs,
job snapshot metadata, step summary counters, and lifecycle timestamps. The step
table stores package-local step order, step ID, status, output reference
metadata, output reference hash, and failure metadata.

Raw error detail is not stored. `error_detail_sha256` preserves correlation and
dedupe value without making the processing tables a raw exception text store.

JSONB is used only for bounded metadata snapshots:

- `job_subject_ref`
- `job_links`

SQLite regression tests will keep equivalent JSON text fixtures in repository
tests while PostgreSQL migration SQL remains canonical.

## Next Slice

Recommended next slice:

- `0183_cx_processing_run_repository_adapter`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_database_schema_foundation.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
pass
```
