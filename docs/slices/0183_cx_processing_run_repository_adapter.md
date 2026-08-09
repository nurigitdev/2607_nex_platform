# Slice 0183: CX Processing Run Repository Adapter

## Scope

Slice 0183 adds repository support for the processing run and step persistence
shape introduced in Slice 0182.

Implemented:

- `build_processing_run_persistence_record()`
- in-memory repository support for processing run records
- SQLAlchemy repository support for `cx_document_processing_runs`
- SQLAlchemy repository support for `cx_document_processing_steps`
- run header upsert with step replacement for queued-to-terminal transitions
- safe metadata regression coverage for builder, in-memory, and SQLite adapter

## Decision

Processing run records must behave like the runtime store: saving the same
`pipeline_run_id` again replaces the latest header and step set. This supports
the normal lifecycle where a run is first stored as `QUEUED` and later updated
to `SUCCEEDED` or `FAILED`.

The adapter stores only the Slice 0181 persistence preview fields. Raw source
text, markdown, chunk text, summary text, vectors, output payloads, and raw
error detail remain outside the repository rows.

## Next Slice

Recommended next slice:

- `0184_cx_processing_run_write_through_integration`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
pass
```
