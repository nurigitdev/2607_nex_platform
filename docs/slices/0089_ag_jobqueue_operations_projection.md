# Slice 0089: AG JobQueue operations projection

## Intent

Slice 0089 gives AG a read-only operations view over service JobQueue state. The
goal is to let operators inspect queued/running/terminal work before deeper
workflow persistence is added.

## Runtime Behavior

`nex_ag.operations` now provides:

- `GET /admin/v1/operations/jobs`
- `build_job_operations_projection`
- `summarize_job_operations`

The projection reads service-owned `common_job.v1` queues through the shared
`JobQueue` port. It accepts service id, status, job type, and limit filters, and
returns:

- latest jobs sorted by updated time
- active and terminal job counts
- per-status counts
- per-service counts
- per-job-type counts
- per-service source availability

The default route registration remains mock-first with in-memory queues. Future
runtime wiring can inject SQLAlchemy-backed per-service queues without changing
the endpoint shape.

## Degraded Sources

If a configured source queue reports `JobQueueError`, AG marks that service as
`UNAVAILABLE` in `source_statuses` and returns a `DEGRADED` projection. If a
known service has no injected queue, AG marks it as `NOT_CONFIGURED`. Unknown
service filters are rejected as request errors.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_runtime_jobs.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
