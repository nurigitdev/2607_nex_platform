# Slice 0168: CX Document Summary Persistence Adapter

## Scope

Slice 0168 adds PostgreSQL-ready persistence for CX document summary metadata
behind the existing ingestion store and repository boundary.

Implemented:

- `build_document_summary_persistence_record()` mapper for public
  `cx_document_summary.v1` records
- in-memory and SQLAlchemy repository support for `cx_document_summaries`
- idempotent lookup keyed by
  `content_object_id + extraction_artifact_id + summary_text_sha256`
- `ContentIngestionStore.save_document_summary()` write-through when a
  persisted extraction artifact is available
- SQLite regression fixture coverage for document summary DDL shape and unique
  key behavior
- audit refresh showing document summary metadata as SQLAlchemy repository ready

## Persistence Boundary

The runtime summary response remains `cx_document_summary.v1`; no public route
response shape changed.

The database rows store only:

- persisted content object and extraction artifact lineage
- prompt template version lineage when available
- summary policy, hash, storage URI, char counts, and limits
- status, language, summarizer model lineage, trace, and timestamps

Full summary text remains outside `cx_document_summaries`. The current
mock-first runtime keeps it in `ContentIngestionStore.summary_texts`; future
private artifact storage can use `summary_storage_uri` without changing the
public summary shape.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_summaries.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
95 passed, 1 warning
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1330 passed, 1 warning
statement_coverage=98.25% threshold=95.00%
branch_coverage=94.18% threshold=85.00%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
```
