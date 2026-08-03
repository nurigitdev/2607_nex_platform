# Slice 0057 MO Provider Runtime Telemetry Snapshot

Status: Implemented.

Backlog candidate: `S6-007` MO provider runtime telemetry snapshot.

Requirement coverage: `MO-FR-001`, `MO-FR-004`, `PLAT-FR-006`,
`PLAT-FR-007`, `TRACE-MO-001`, `AG-FR-001`.

## Scope

Slice 0057 adds a minimal runtime telemetry surface for live MO provider
adapters:

- Remote embedding, reranker, and generation executions now update an
  in-memory, process-local telemetry bucket after the provider endpoint is
  configured and a live request is attempted.
- Successful normalized calls increment success counters and record the last
  safe status/latency snapshot.
- Provider route failures increment failure counters and preserve retryable,
  degraded, failure kind, error code, and upstream status metadata.
- Malformed provider responses are counted as retryable degraded failures
  because caller-side fallback/recovery may still be useful.
- `GET /api/v1/provider-telemetry` returns configured capability rows plus
  runtime counters, filtered by optional `capability`.
- The public telemetry payload excludes provider URLs, API keys, model paths,
  and raw upstream payloads.

This is intentionally not a durable metrics backend. It gives AG and operators a
stable read model for the first live DGX integration pass while keeping
persistence and external metrics export out of the early slice.

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

Telemetry tests reset the in-memory store between test cases and use fake
`httpx` responders, so live provider endpoints and API keys stay outside
committed files.
