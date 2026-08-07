# Slice 0130: Job Control OpenAPI and Smoke Evidence

## Scope

Slice 0130 freezes the job control surfaces introduced in Slices 0125-0128 as
OpenAPI contract entries and adds a mock-first smoke evidence pack.

Implemented:

- AG OpenAPI paths for operator-facing job cancel and retry dispatch
- AG `ag_job_control_dispatch.v1` response schema
- CX OpenAPI paths for service-local internal job read, cancel, and retry
- `scripts/smoke/run_ag_job_control_smoke.py`
- quality gate execution of the AG job control smoke

## Contract Boundary

AG owns the operator-facing control surface:

```text
POST /admin/v1/operations/jobs/{service_id}/{job_id}/cancel
POST /admin/v1/operations/jobs/{service_id}/{job_id}/retry
```

CX documents the target service-local surface that AG dispatches to:

```text
GET /internal/v1/jobs/{job_id}
POST /internal/v1/jobs/{job_id}/cancel
POST /internal/v1/jobs/{job_id}/retry
```

The service-local job projection remains payload-redacted. Operator replay of
terminal dead-letter jobs is still a separate audited workflow.

## Smoke Evidence

The smoke runs without external network or PostgreSQL dependencies. It connects
an AG app and a CX app in-process with FastAPI `TestClient` and validates:

- AG cancel dispatch projection
- AG retry dispatch projection
- CX service-local queue mutation
- AG job control audit events
- payload redaction in operator-facing evidence

Summary command:

```bash
./.venv/bin/python scripts/smoke/run_ag_job_control_smoke.py --summary
```

Expected summary:

```text
ag_job_control_smoke=pass actions=2 audit_events=2 cancel_status=CANCELLED retry_status=QUEUED
```

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_contract_validation.py
./.venv/bin/python scripts/smoke/run_ag_job_control_smoke.py --summary
./.venv/bin/python scripts/quality/validate_contracts.py
```

