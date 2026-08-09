# Slice 0186: CX Processing Persisted Read-Model Query Foundation

## Scope

Slice 0186 adds the persisted read-model query foundation for CX document
processing runs after PostgreSQL write-through and live test DB smoke evidence.

Implemented:

- `nex_cx.processing_read_model`
- processing run query filter normalization
- safe read-model projection for list/detail callers
- `CxContentRepository.list_processing_run_records()`
- SQLAlchemy and in-memory repository implementations
- regression coverage for filters, ordering, limit caps, step omission, and
  private payload redaction

## Decision

This slice intentionally does not wire the public CX service route yet. It
stabilizes the read boundary first so the next slice can adapt
`GET /api/v1/documents/{document_id}/processing` to prefer persisted rows in
PostgreSQL mode without duplicating query or projection rules inside the route.

Supported query filters:

- `document_id`
- `status`
- `trace_id`
- `request_id`
- `job_id`
- `limit`
- `include_steps`

The list query orders rows by `updated_at DESC, pipeline_run_id DESC`. List
views can request `include_steps=False`; detail views can keep steps included.
The read-model exposes hashes, references, counters, job snapshots, and
timestamps only. It does not copy raw source text, output payloads, or raw error
details into the projection.

## Next Slice

Recommended next slice:

- `0187_cx_processing_run_service_api_persisted_wiring`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_processing_read_model.py tests/test_nex_cx_repository.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
pass
```

Observed targeted result:

```text
126 passed
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1419 passed
statement_coverage=98.06%
branch_coverage=93.69%
contract_validation=pass
```
