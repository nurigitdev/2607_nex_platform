# nex-mo

NeX Model Operations service.

Owned database env: `NEX_MO_DATABASE_URL`.

Model profile defaults:

- Model root: `NEX_MO_MODEL_ROOT` or `/data/nex-platform/models`
- Embedding: `qwen3_embedding_4b_bf16` at `qwen3-embedding-4b-bf16`
- Reranker: `qwen3_reranker_0_6b_bf16` at
  `qwen3-reranker-0.6b-bf16`
- Generation primary: `qwen3_5_122b_a10b_nvfp4` at
  `qwen3.5-122b-a10b-nvfp4`
- Generation candidate: `qwen3_6_27b_nvfp4` at `qwen3.6-27b-nvfp4`
- Generation planned candidate: `k_ai_generation_candidate` for a domestic
  K-AI model evaluation
- Provider mode: `NEX_MO_PROVIDER_MODE=mock` until DGX-spark is reachable
- Live DGX preflight stays opt-in with `NEX_MO_LIVE_PREFLIGHT=1`; it is not
  part of the default regression gate.
- Local live config guard can be run without network calls. It verifies that
  selected execution models and live preflight expected models agree, including
  the current DGX-Spark reranker target `Qwen3-Reranker-0.6B`.
- Protected live profiles are split by provider shape:
  - `dgx_vllm`: canonical direct vLLM profile for embedding, reranking, and
    generation.
  - `dgx`: deprecated alias for `dgx_vllm`.
  - `dgx_pcx_legacy`: explicit compatibility profile for older NeX-PCX
    embedding/reranker request shapes.
- Live preflight request shapes:
  - Current DGX embedding/reranker providers are direct vLLM pooling servers.
  - Embedding: `POST` to `NEX_MO_REMOTE_EMBEDDING_URL`. The generic shape is
    OpenAI-compatible `model` and `input`.
  - Reranker: `POST` to `NEX_MO_REMOTE_RERANKER_URL`. The generic shape uses
    `model`, `query`, `documents`, and `top_n`; MO normalizes vLLM native
    `relevance_score` results when present.
  - The protected DGX-PCX profile remains available for legacy providers with
    `nex_pcx_embeddings_v1` and `nex_pcx_rerank_v1`.
  - vLLM model catalog: `GET` to `NEX_MO_VLLM_MODELS_URL`, or
    `NEX_MO_VLLM_BASE_URL` plus `/v1/models`.
- Live embedding execution uses the same `/api/v1/embeddings` MO API that CX
  already calls. Set `NEX_MO_PROVIDER_MODE=live` and
  `NEX_MO_REMOTE_EMBEDDING_URL`; MO translates `inputs` to OpenAI-compatible
  `input`, or to the configured DGX-PCX shape, and returns the existing
  normalized MO response shape.
- Live reranker execution uses the same `/api/v1/rerank` MO API. Set
  `NEX_MO_PROVIDER_MODE=live` and `NEX_MO_REMOTE_RERANKER_URL`; MO translates
  `query`, `documents`, and optional `top_n` to the configured remote reranker
  shape and normalizes scores back to the existing MO result shape. Direct vLLM
  reranker responses may use `relevance_score` and `document.text`; both are
  normalized by MO.
- Live generation execution uses the same `/api/v1/generations` MO API. Set
  `NEX_MO_PROVIDER_MODE=live` and `NEX_MO_VLLM_BASE_URL` or
  `NEX_MO_VLLM_CHAT_COMPLETIONS_URL`; MO sends OpenAI-compatible
  `POST /v1/chat/completions` and normalizes choices, finish reason, usage, and
  runtime metadata back to the existing MO generation response shape.
- Live provider failures use a shared safe taxonomy. Timeouts, connection
  errors, HTTP `429`, HTTP `5xx`, and malformed provider responses are treated
  as retryable degraded failures; upstream `4xx` responses are safe non-retryable
  `502` failures. Problem responses expose `details.degraded=true` only for
  degraded failures and never include endpoint URLs or API keys.
- Provider runtime telemetry is available at `GET /api/v1/provider-telemetry`.
  The snapshot is in-memory, process-local, and read-only. It reports configured
  capability rows plus success/failure counters and last safe failure metadata;
  it does not expose provider URLs, API keys, or raw provider payloads.
- Direct vLLM HTTP APIs do not expose loaded parameter dtype. BF16 evidence for
  embedding/reranker providers must be collected by inspecting vLLM launch args
  or logs and confirming `--dtype bfloat16`.
- Safe config and profile evidence treats `dgx_vllm` as the canonical lane and
  hides NeX-PCX request options unless a PCX request shape is explicitly active.
  The `dgx_pcx_legacy` profile remains available, but it is not the default for
  new work.
- Local live config hardening treats `dgx_vllm` as the default protected
  profile. Legacy NeX-PCX embedding/reranker request shapes fail unless
  `NEX_MO_PROTECTED_LIVE_PROFILE=dgx_pcx_legacy`, and live timeout values must
  be positive.

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /internal/v1/auth/service-claim`
- `GET /api/v1/provider-routes`
- `GET /api/v1/provider-profiles`
- `GET /api/v1/provider-telemetry`
- `POST /api/v1/embeddings`
- `POST /api/v1/rerank`
- `POST /api/v1/generations`

Manual live preflight:

```bash
./.venv/bin/python scripts/smoke/check_local_live_provider_config.py --summary
NEX_MO_PROVIDER_MODE=live ./.venv/bin/python scripts/smoke/check_local_live_provider_config.py --summary
NEX_MO_PROTECTED_LIVE_PROFILE=dgx ./.venv/bin/python scripts/smoke/run_protected_dgx_live_profile.py --summary
NEX_MO_PROTECTED_LIVE_PROFILE=dgx ./.venv/bin/python scripts/smoke/run_protected_dgx_live_profile.py --output reports/live/protected-dgx-live-profile.json --summary
NEX_MO_PROVIDER_MODE=live ./.venv/bin/python scripts/smoke/check_local_live_provider_config.py --output reports/live/local-live-provider-config.json --summary
NEX_MO_LIVE_PREFLIGHT=1 ./.venv/bin/python scripts/smoke/run_dgx_live_provider_preflight.py --summary
NEX_MO_LIVE_PREFLIGHT=1 ./.venv/bin/python scripts/smoke/run_dgx_live_provider_preflight.py --evidence-output reports/live/dgx-provider-preflight.json --summary
NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE=1 ./.venv/bin/python scripts/smoke/run_protected_remote_provider_live_smoke.py --summary
NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE=1 ./.venv/bin/python scripts/smoke/run_protected_remote_provider_live_smoke.py --evidence-output reports/live/protected-remote-provider-live-smoke.json --summary
NEX_COMPAT_LIVE_SMOKE=1 ./.venv/bin/python scripts/smoke/run_compatible_provider_live_smoke.py --summary
NEX_COMPAT_LIVE_SMOKE=1 ./.venv/bin/python scripts/smoke/run_compatible_provider_live_smoke.py --evidence-output reports/live/compatible-vllm-provider-smoke.json --summary
```

`run_protected_dgx_live_profile.py` is the preferred operator entrypoint. Use
`NEX_MO_PROTECTED_LIVE_PROFILE=dgx_vllm` for the canonical direct vLLM path. It
sets the underlying local-live and live-preflight flags in an isolated
environment copy, runs the local config guard first, and only then calls DGX.

The config snapshot writer adds `local_live_provider_config_snapshot.v1`
redaction metadata. The live preflight evidence writer adds
`dgx_live_provider_preflight_evidence.v1` redaction metadata. The protected
remote provider live smoke adds
`protected_remote_provider_live_smoke_evidence.v1` and sends minimal live
embedding, reranker, and generation requests through the MO remote-provider
adapters. These evidence writers refuse to write if configured endpoint or
API-key environment values appear in the serialized output.

The older `NEX_MO_LIVE_EMBEDDING_HEALTH_URL`,
`NEX_MO_LIVE_RERANKER_HEALTH_URL`, and `NEX_MO_LIVE_VLLM_MODELS_URL` names
remain supported as deprecated fallback aliases. Prefer
`NEX_MO_REMOTE_EMBEDDING_URL`, `NEX_MO_REMOTE_RERANKER_URL`,
`NEX_MO_VLLM_BASE_URL`, `NEX_MO_VLLM_MODELS_URL`, and `NEX_MO_VLLM_API_KEY` in
`.env.local` or the shell before running live checks. Current direct vLLM
embedding/reranker providers should use
`NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE=openai_embeddings` and
`NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE=rerank`. Legacy DGX-PCX providers should
use `nex_pcx_embeddings_v1` and `nex_pcx_rerank_v1`. Do not commit real API
keys.
