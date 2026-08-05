# Slice 0104: AG Job Detail Lifecycle Timeline

## Scope

Slice 0104 adds a service-scoped AG job detail endpoint:

```text
GET /admin/v1/operations/jobs/{service_id}/{job_id}
```

The endpoint lets operators inspect one `common_job.v1` record without scanning
the job list projection.

## Response Shape

The projection schema version is:

```text
ag_job_operation_detail_projection.v1
```

The response includes:

- the selected job with its owning `service_id`
- a compact summary of job id, job type, status, trace id, subject ref, attempt
  count, and timeline status
- a lifecycle timeline assembled from matching operational events

## Lifecycle Timeline

Timeline matching is intentionally conservative. AG queries the operational
event store by the job trace id and then keeps events where either:

- `details.job_id` matches the selected job id
- `subject_ref` matches the selected job subject ref

This keeps unrelated events from the same trace out of the job detail view while
still supporting early CX processing events that carry subject refs before every
event family has a job id.

Timeline source states are explicit:

- `READY`: event source was queried successfully
- `NOT_CONFIGURED`: no event source was supplied for detail projection
- `UNAVAILABLE`: event source raised an operational event store error

The job detail itself remains available when the timeline source is unavailable.

## Problem Responses

- unsupported service id: `ag.job_service_invalid`
- missing service job source: `ag.job_source_not_configured`
- missing job id: `ag.job_not_found`
- source read failure: the underlying job queue error code

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_runtime_app.py
```

Observed result:

```text
85 passed
```
