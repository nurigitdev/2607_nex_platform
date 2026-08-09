# Slice 0173: CX Retrieval Package Repository Adapter

## Scope

Slice 0173 adds retrieval package persistence methods behind
`CxContentRepository`.

Implemented:

- `save_retrieval_package_record`
- `get_retrieval_package_record`
- `find_retrieval_package_record_by_hash`
- SQLAlchemy insert/select adapters for `cx_retrieval_packages` and
  `cx_retrieval_evidence_items`
- in-memory repository parity for regression testing
- `build_retrieval_package_persistence_record()`

## Decision

The repository stores only durable metadata. Runtime package fields such as
`query_text` and `evidence_items[].text` are transformed to SHA-256 hashes and
bounded previews before insert. Query embedding persistence records use the
runtime `provided` and `vector_dimension` keys while preserving compatibility
with older preview key names.

`package_hash` is the idempotency key for duplicate retrieval package writes.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_retrieval_persistence.py
```

Observed result:

```text
99 passed
```
