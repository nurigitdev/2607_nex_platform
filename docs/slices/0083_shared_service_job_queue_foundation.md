# Slice 0083: Shared service JobQueue foundation

## Intent

Slice 0083 introduces a common JobQueue foundation before wiring CX processing
to it. The goal is to make job lifecycle semantics shared across OA, AG, AE, CX,
and MO while keeping this slice mock-first and regression-stable.

## Runtime Behavior

`nex_runtime.jobs` now provides:

- `common_job.v1` aligned job construction
- subject reference construction
- status and field validation
- explicit transition rules for `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, and
  `CANCELLED`
- idempotent in-memory enqueue by `job_type + idempotency_key`
- safe copy-returning reads
- status summaries for future AG monitoring views

CX ingestion job construction now uses the shared common job builder while
preserving the existing API response shape.

## Database Shape

Every service gets an `0083_service_job_queue_foundation.sql` migration with a
service-owned `service_jobs` table. The table stores:

- common job identity and lifecycle fields
- trace, request, subject, idempotency, attempt, and retry fields
- JSONB links, payload, and error slots
- availability and lock fields for later worker execution
- status/type/trace/subject indexes

SQL write-through is intentionally deferred. Slice 0084 will connect CX document
processing to the common JobQueue port first.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_jobs.py tests/test_nex_cx_ingestion.py tests/test_database_schema_foundation.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
