# Slice 0056 Provider Failure Taxonomy and Retry/Degrade Policy

Status: Implemented.

Backlog candidate: `S6-006` Provider failure taxonomy and retry/degrade policy.

Requirement coverage: `MO-FR-001`, `MO-FR-004`, `PLAT-FR-006`,
`PLAT-FR-007`, `TRACE-MO-001`.

## Scope

Slice 0056 standardizes how MO classifies live remote provider failures before
the adapters are used by CX and AE flows:

- Timeouts become `*_timeout` with HTTP `504`, `retryable=true`, and
  `degraded=true`.
- Connection-level `httpx` errors become `*_unavailable` with HTTP `503`,
  `retryable=true`, and `degraded=true`.
- Remote HTTP `429` becomes `*_throttled` with HTTP `429`, `retryable=true`,
  and `degraded=true`.
- Remote HTTP `5xx` becomes `*_http_error` with HTTP `503`, `retryable=true`,
  and `degraded=true`.
- Remote HTTP `4xx` becomes `*_http_error` with HTTP `502`,
  `retryable=false`, and no degraded marker.
- Invalid JSON or malformed provider response shapes become
  `*_response_invalid` with HTTP `502`, `retryable=true`, and
  `degraded=true`.
- API problem responses include `details.degraded=true` only when the failure
  can be treated as degraded by callers.
- Safe summaries expose failure kind, public error code, local status,
  retryability, degraded state, and upstream status code when available. They do
  not expose provider URLs, model paths, or API keys.

This slice intentionally does not add automatic retry loops. It freezes the
decision taxonomy that later retry, recovery, readiness, and AG telemetry slices
can consume.

## Files

- `services/nex-mo/nex_mo/remote_provider.py`
- `services/nex-mo/nex_mo/providers.py`
- `services/nex-mo/README.md`
- `tests/test_nex_mo_remote_provider.py`
- `tests/test_nex_mo_providers.py`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_nex_mo_remote_provider.py tests/test_nex_mo_providers.py
scripts/quality/run_quality_gate.sh
```

The failure tests use fake `httpx` responders and assert that endpoint URLs and
API keys stay out of public response bodies.
