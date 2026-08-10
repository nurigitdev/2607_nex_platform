# Slice 0187: CX Processing Run Service API Persisted Wiring

## Scope

Slice 0187 wires the CX document processing service API to the persisted
processing run read boundary introduced in Slice 0186.

Implemented:

- `GET /api/v1/documents/{document_id}/processing` persisted repository lookup
- safe projection through `project_processing_run_record()`
- in-memory runtime record fallback for local regression mode and pre-persistence
  records
- repository-unavailable problem response mapping
- `nex_cx.main` bootstrap for `SqlAlchemyCxContentRepository` in PostgreSQL
  persistence mode
- processing persistence decision status update to
  `service_api_persisted_read_ready_ag_pending`

## Decision

The detail endpoint now prefers a persisted processing run row when a
repository is explicitly supplied or when the service app is running in
PostgreSQL persistence mode with an API session factory. Persisted responses use
the read-model projection shape and expose run headers, job references, step
counters, output reference hashes, and error hashes only.

If no persisted row is available, the endpoint returns the existing runtime
pipeline record from `ContentIngestionStore`. This keeps SQLite/in-memory
regression tests, local mock flows, and records created before persistence
write-through compatible.

Repository errors are not hidden by the fallback path. They return a structured
problem response so PostgreSQL smoke and operator-facing diagnostics can catch
DB connectivity or migration issues early.

## Next Slice

Recommended next slice:

- `0188_cx_processing_run_operations_projection`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_processing.py tests/test_nex_cx_processing_read_model.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
pass
```

Observed targeted result:

```text
53 passed
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1425 passed
statement_coverage=98.06%
branch_coverage=93.68%
contract_validation=pass
```
