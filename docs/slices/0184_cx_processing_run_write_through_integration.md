# Slice 0184: CX Processing Run Write-Through Integration

## Scope

Slice 0184 wires the processing run repository adapter into the runtime
`ContentIngestionStore` save path.

Implemented:

- `ContentIngestionStore.save_document_processing_run()` write-through
- content-ref guard before writing to the repository
- safe persistence record generation through
  `build_processing_run_persistence_record()`
- regression coverage for successful write-through and memory-only fallback
- CX persistence audit status update to
  `write_through_ready_postgres_smoke_pending`

## Decision

Processing run persistence is now best-effort behind the existing runtime store.
The in-memory record remains the source returned to callers in this slice. The
repository write path is used only when the document already has persisted
content lineage.

This keeps early and metadata-only processing paths stable while enabling the
normal uploaded-document pipeline to write processing run and step metadata to
SQLAlchemy-backed repositories.

## Next Slice

Recommended next slice:

- `0185_cx_processing_postgresql_smoke_evidence`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
pass
```
