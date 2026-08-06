# Slice 0127: AG Job Operation Control Endpoints

## Scope

Slice 0127 exposes AG operator-facing job control endpoints that dispatch to the
service-local job control API introduced in Slice 0125.

Implemented:

- `POST /admin/v1/operations/jobs/{service_id}/{job_id}/cancel`
- `POST /admin/v1/operations/jobs/{service_id}/{job_id}/retry`
- `ag_job_control_dispatch.v1` wrapper projection
- request id and traceparent propagation into the AG job control client
- AG-side service id and payload validation
- downstream service error mapping into problem responses

## Boundary

These endpoints do not mutate AG's read-only operations source adapters and do
not write directly into another service database. AG validates and dispatches;
the target service owns the JobQueue transition through its internal API.

## Payload

Cancel accepts an optional `observed_at` timestamp. Retry accepts optional
`error_code`, `detail`, and `observed_at` fields. Empty strings are rejected by
AG before dispatch.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_job_control.py
```
