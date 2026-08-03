# Slice 0058 AG MO Provider Readiness Projection

Status: Implemented.

Backlog candidate: `S6-008` AG MO provider readiness projection.

Requirement coverage: `AG-FR-001`, `MO-FR-001`, `MO-FR-004`,
`PLAT-FR-006`, `PLAT-FR-007`, `TRACE-MO-001`.

## Scope

Slice 0058 adds an AG operator-facing projection over MO provider telemetry:

- `GET /admin/v1/readiness/providers` is registered with the existing AG
  readiness route family.
- AG reads MO's `GET /api/v1/provider-telemetry` using a mock service token for
  the `nex-ag -> nex-mo` service call.
- The projection normalizes provider rows into safe fields: capability,
  configured state, request shape, model name/revision, deployment ID, counters,
  and last public failure metadata.
- The projection summarizes configured/unconfigured rows, total requests,
  successes, failures, retryable failures, and degraded counts.
- `live` mode with any unconfigured provider row becomes `NOT_READY`.
- Any malformed telemetry item, failure count, or degraded count becomes
  `DEGRADED`.
- MO telemetry fetch errors or invalid payloads become `UNAVAILABLE`.
- Provider URLs, API keys, model paths, and raw upstream payloads are not copied
  into the AG projection.

The endpoint is read-only and does not read MO databases. It keeps AG aligned
with the service-owned API boundary established by the first readiness slice.

## Files

- `services/nex-ag/nex_ag/readiness.py`
- `services/nex-ag/README.md`
- `tests/test_nex_ag_readiness.py`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_nex_ag_readiness.py
scripts/quality/run_quality_gate.sh
```

HTTP client tests use fake `httpx` responders and a fake token, so live DGX or
MO credentials are not required.
