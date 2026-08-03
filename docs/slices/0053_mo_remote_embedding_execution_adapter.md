# Slice 0053 MO Remote Embedding Execution Adapter

Status: Implemented.

Backlog candidate: `S6-003` MO remote embedding execution adapter.

Requirement coverage: `MO-FR-001`, `MO-FR-002`, `MO-FR-004`, `PLAT-FR-006`,
`PLAT-FR-007`.

## Scope

Slice 0053 connects the existing MO embedding API to a remote HTTP embedding
provider when `NEX_MO_PROVIDER_MODE=live`:

- `/api/v1/embeddings` keeps the existing MO request/response contract used by
  CX.
- MO translates caller `inputs` into an OpenAI-compatible remote
  `POST /v1/embeddings` request with `model` and `input`.
- Remote model, model revision, deployment ID, endpoint, API key, and timeout
  are driven by environment variables.
- Provider-private caller fields such as raw endpoint URLs and API keys are
  rejected before any remote call.
- Remote response data is normalized into the existing MO embedding response
  shape with `alias`, `model_revision`, `deployment_id`, `data`, and `usage`.
- HTTP, timeout, connection, invalid JSON, count mismatch, and malformed vector
  responses raise safe `ProviderRouteError` values without exposing endpoint
  URLs, API keys, or response bodies.

Mock mode remains the default and continues to be the only default quality-gate
runtime path.

## Files

- `services/nex-mo/nex_mo/remote_provider.py`
- `services/nex-mo/nex_mo/providers.py`
- `tests/test_nex_mo_remote_provider.py`
- `tests/test_nex_mo_providers.py`
- `.env.example`
- `services/nex-mo/README.md`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_nex_mo_remote_provider.py tests/test_nex_mo_providers.py
scripts/quality/run_quality_gate.sh
```

Remote execution tests use fake `httpx` responders. Real DGX credentials stay in
`.env.local` or the shell and are not required for this slice.
