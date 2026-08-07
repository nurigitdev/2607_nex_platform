# Slice 0132: AG Dead-Letter Replay Dispatch Endpoint

## Scope

Slice 0132 adds the AG operator-facing dispatch path for service-local
dead-letter replay.

Implemented:

- `AgJobControlClient.replay_job()`
- `HttpAgJobControlClient.replay_job()`
- `POST /admin/v1/operations/jobs/{service_id}/{job_id}/replay`
- AG replay dispatch success projection through `ag_job_control_dispatch.v1`
- AG replay dispatch audit events through existing job-control audit taxonomy

## Request

AG requires the same replay fields as the service-local API:

```text
replay_job_id
idempotency_key
requested_by
reason
observed_at=<optional>
```

Missing or blank replay fields return `ag.job_control_payload_invalid` before
AG dispatches to the target service.

## Dispatch

The AG endpoint uses the existing service-local job control client boundary. It
does not read or write another service database directly.

Successful dispatches are audited as:

```text
event_type=ag.job_control.succeeded
details.action=replay
details.target_service_id=<service_id>
details.target_job_id=<source job id>
```

Failed dispatches reuse the existing `ag.job_control.failed` path.

## Boundary

This slice wires runtime behavior and regression tests. OpenAPI and smoke
evidence for replay remain a follow-up contract freeze.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_job_control.py tests/test_nex_ag_operations.py
```

