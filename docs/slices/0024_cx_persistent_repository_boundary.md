# Slice 0024 CX Persistent Repository Boundary

Status: Implemented.

Backlog candidate: `S3-004` CX persistent repository boundary for source file
and content object records.

Requirement coverage: `CX-FR-001`, `CX-FR-002`, `TRACE-PLAT-001`.

## Scope

Slice 0024 introduces a CX repository boundary that separates global source file
metadata from user-owned logical content objects:

- `source_file` records represent file bytes and storage metadata.
- `content_object` records represent tenant/user-owned document registrations.
- The in-memory adapter deduplicates source file records by `source_sha256`.
- Active content objects can be looked up by
  `tenant_id + owner_user_id + source_sha256`.
- `ContentIngestionStore` now persists private repository records while keeping
  the public upload registration contract unchanged.

The repository adapter is still mock/in-memory. PostgreSQL write-through can be
added after the migration runner is exercised against local development
databases.

## Files

- `services/nex-cx/nex_cx/repository.py`
- `services/nex-cx/nex_cx/ingestion.py`
- `tests/test_nex_cx_repository.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover source file record mapping, content object owner scope,
source SHA dedupe, active content lookup, and no raw source text leakage through
repository records.
