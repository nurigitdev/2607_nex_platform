# Slice 0084: CX processing pipeline JobQueue bridge

## Intent

Slice 0084 connects the existing CX document processing pipeline to the shared
JobQueue port introduced in Slice 0083. The pipeline still executes
synchronously in mock/local tests, but each run now leaves a common job lifecycle
snapshot.

## Runtime Behavior

- `run_document_processing_pipeline` creates a `cx.document_processing` common
  job for each pipeline run.
- Job idempotency uses the deterministic `pipeline_run_id`.
- The normal lifecycle is `QUEUED -> RUNNING -> SUCCEEDED`.
- Failed pipelines transition the job to `FAILED` and expose safe job details in
  problem+json details.
- If the same request/trace pair reaches an already-terminal job, CX returns the
  previously stored pipeline run instead of executing the expensive steps again.
- Pipeline records include a safe `job` snapshot with common job identity,
  status, subject, attempts, links, and timestamps.

## Deferred

The bridge still uses the in-memory queue port. PostgreSQL write-through to the
`service_jobs` table remains deferred until repositories adopt the shared queue
port.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_cx_processing.py tests/test_nex_runtime_jobs.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
