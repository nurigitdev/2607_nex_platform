# Slice 0128: Job Control Audit Operational Events

## Scope

Slice 0128 records AG job control dispatch outcomes as operational events.

Implemented:

- `ag.job_control.succeeded`
- `ag.job_control.failed`
- shared operational event taxonomy entries for both event types
- AG-local audit event emission for cancel/retry dispatch success
- AG-local audit event emission for dispatch failure
- safe audit emission so control responses are not blocked by event-store errors

## Boundary

AG operations source registries remain read-only projections over service-owned
databases. Job control audit events are written to AG's own operational event
store, not to the target service's database and not to the cross-service
read-only registry.

## Event Details

Success events include:

```text
target_service_id
target_job_id
action
dispatch_status
job_status
service_job_control_schema_version
```

Failure events include:

```text
target_service_id
target_job_id
action
dispatch_status
error_code
status_code
retryable
```

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_runtime_operational_events.py tests/test_nex_runtime_app.py
```
