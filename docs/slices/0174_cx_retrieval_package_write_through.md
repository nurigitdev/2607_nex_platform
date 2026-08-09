# Slice 0174: CX Retrieval Package Write-Through

## Scope

Slice 0174 wires retrieval package metadata persistence into
`ContentIngestionStore.save_retrieval_package()`.

Implemented:

- retrieval package write-through to `CxContentRepository`
- lineage guard requiring persisted content/chunk rows for evidence packages
- no-answer package persistence without evidence references
- regression coverage for persisted, no-answer, and skipped write-through paths

## Decision

Retrieval package persistence is best-effort behind the store boundary. Packages
with evidence are persisted only when their `content_object_id` and `chunk_id`
can be resolved to already-persisted CX content/chunk rows. This keeps existing
mock-only retrieval flows working while enabling durable records for the
PostgreSQL-backed processing path.

`NO_ANSWER` packages with no evidence can be persisted without content/chunk
lineage because they are still useful for AG/debug history and do not reference
document snippets.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_retrieval.py tests/test_nex_cx_retrieval_persistence.py
```

Observed result:

```text
184 passed, 1 warning
```
