# Slice 0125: Service-Local Job Control API Foundation

## Scope

Slice 0125 adds an internal service-local job control API that lets each backend
service expose read/cancel/retry controls for jobs owned by that service's
JobQueue adapter.

Implemented:

- `service_job_control.v1` response shape
- `GET /internal/v1/jobs/{job_id}`
- `POST /internal/v1/jobs/{job_id}/cancel`
- `POST /internal/v1/jobs/{job_id}/retry`
- shared route registration helper for all five service entrypoints
- service-claim authorization with the target service as audience
- conservative job projection that omits job payloads

## Boundary

AG should not update another service database directly. This API gives AG and
future operator tools a service-owned control surface while keeping persistence
ownership local to `nex-oa`, `nex-ag`, `nex-ae-api`, `nex-cx`, and `nex-mo`.

The control API intentionally exposes only active-job cancel and RUNNING-job
retry. Operator requeue of terminal dead-letter jobs is left for a later slice
because it needs explicit audit, authorization, and replay policy decisions.

## Response Shape

```text
job_control_schema_version=service_job_control.v1
service_id=<target service>
action=read|cancel|retry
job=<payload-redacted common_job projection>
controls.can_cancel=<bool>
controls.can_retry=<bool>
controls.dead_lettered=<bool>
controls.allowed_actions=[read, cancel?, retry?]
```

`payload` is excluded from the projection so document paths, request bodies, or
future provider inputs do not leak through this generic internal control API.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_job_control.py tests/test_nex_runtime_app.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
