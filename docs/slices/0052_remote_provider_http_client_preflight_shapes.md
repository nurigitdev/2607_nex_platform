# Slice 0052 Remote Provider HTTP Client Preflight Shapes

Status: Implemented.

Backlog candidate: `S6-002` remote provider HTTP client foundation and live
preflight request shape cleanup.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0052 turns the 0051 live DGX smoke into a provider-shape aware HTTP client
foundation:

- `nex_mo.remote_provider` builds env-driven preflight configs for embedding,
  reranking, and vLLM model catalog checks.
- Embedding live preflight uses OpenAI-compatible `POST /v1/embeddings` shape
  with `model` and `input`.
- Reranker live preflight uses `POST /v1/rerank` shape with `model`, `query`,
  `documents`, and `top_n`.
- vLLM live preflight uses OpenAI-compatible `GET /v1/models`; when
  `NEX_MO_VLLM_MODELS_URL` is absent it derives the endpoint from
  `NEX_MO_VLLM_BASE_URL`.
- The live generation model default now follows the selected MO generation
  profile instead of requiring every catalog candidate to be served at once.
- Preflight evidence still redacts endpoint URLs, API keys, and response
  bodies. It records env key, method, request shape, authorization presence,
  expected model names, and structural validation facts.
- Deprecated 0051 endpoint env names remain supported as fallback aliases for
  existing local `.env.local` files.

The default regression path remains mock-first. Real DGX/vLLM calls stay manual
and opt-in with `NEX_MO_LIVE_PREFLIGHT=1`.

## Files

- `services/nex-mo/nex_mo/remote_provider.py`
- `scripts/smoke/run_dgx_live_provider_preflight.py`
- `tests/test_nex_mo_remote_provider.py`
- `tests/test_dgx_live_provider_preflight.py`
- `.env.example`
- `services/nex-mo/README.md`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_nex_mo_remote_provider.py tests/test_dgx_live_provider_preflight.py
scripts/quality/run_quality_gate.sh
./.venv/bin/python scripts/smoke/run_dgx_live_provider_preflight.py --summary
```

The live preflight summary should stay skipped unless live env vars are
explicitly enabled. Real endpoint values and API keys belong in `.env.local` or
the shell, not committed docs.
