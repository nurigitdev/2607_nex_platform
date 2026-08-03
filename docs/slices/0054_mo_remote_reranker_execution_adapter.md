# Slice 0054 MO Remote Reranker Execution Adapter

Status: Implemented.

Backlog candidate: `S6-004` MO remote reranker execution adapter.

Requirement coverage: `MO-FR-001`, `MO-FR-002`, `MO-FR-004`, `PLAT-FR-006`,
`PLAT-FR-007`.

## Scope

Slice 0054 connects the existing MO rerank API to a remote HTTP reranker when
`NEX_MO_PROVIDER_MODE=live`:

- `/api/v1/rerank` keeps the existing MO request/response contract.
- MO translates caller `query`, `documents`, and optional `top_n` into the
  remote `POST /v1/rerank` request shape.
- Remote model, model revision, deployment ID, endpoint, API key, and timeout
  are driven by environment variables.
- Remote results are normalized from either `results` or `data`, and score can
  arrive as `score` or `relevance_score`.
- Normalized results are sorted by descending score and include `index`,
  `score`, and `document`.
- Provider-private caller fields are rejected before any remote call.
- HTTP, timeout, connection, invalid JSON, missing results, invalid index, and
  malformed score responses raise safe errors without exposing endpoint URLs,
  API keys, or response bodies.

Mock mode remains the default runtime path for CI and local regression.

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

Remote reranker tests use fake `httpx` responders. Real DGX endpoint values stay
outside committed files.
