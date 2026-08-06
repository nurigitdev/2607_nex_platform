# Slice 0126: AG Service-Local Job Control Client Foundation

## Scope

Slice 0126 adds the AG-side HTTP client foundation for service-local job control
without adding AG operator endpoints yet.

Implemented:

- `AgJobControlClient` protocol
- `HttpAgJobControlClient`
- `AgJobControlError`
- service base URL env resolution
- AG-to-service token env resolution
- mock service-token fallback for local regression
- request headers for request id, traceparent, and caller service id

## Boundary

AG operations projections can read service-owned PostgreSQL sources through
read-only adapters, but control actions should call each service's
`/internal/v1/jobs/...` endpoint. This keeps AG from writing directly into
another service database while still allowing a future operator surface to
request cancel or retry.

## Environment

Base URL env names follow service package conventions:

```text
NEX_OA_BASE_URL
NEX_AG_BASE_URL
NEX_AE_API_BASE_URL
NEX_CX_BASE_URL
NEX_MO_BASE_URL
```

Optional AG-to-service token env names:

```text
NEX_AG_TO_OA_SERVICE_TOKEN
NEX_AG_TO_AG_SERVICE_TOKEN
NEX_AG_TO_AE_SERVICE_TOKEN
NEX_AG_TO_CX_SERVICE_TOKEN
NEX_AG_TO_MO_SERVICE_TOKEN
```

`NEX_AG_JOB_CONTROL_TIMEOUT_SECONDS` controls the HTTP timeout. The default is
5 seconds.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_job_control.py
```
