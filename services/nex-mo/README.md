# nex-mo

NeX Model Operations service.

Owned database env: `NEX_MO_DATABASE_URL`.

Model profile defaults:

- Model root: `NEX_MO_MODEL_ROOT` or `/data/nex-platform/models`
- Embedding: `qwen3_embedding_4b_bf16` at `qwen3-embedding-4b-bf16`
- Reranker: `qwen3_reranker_4b_bf16` at `qwen3-reranker-4b-bf16`
- Generation primary: `qwen3_5_122b_a10b_nvfp4` at
  `qwen3.5-122b-a10b-nvfp4`
- Generation candidate: `qwen3_6_27b_nvfp4` at `qwen3.6-27b-nvfp4`
- Generation planned candidate: `k_ai_generation_candidate` for a domestic
  K-AI model evaluation
- Provider mode: `NEX_MO_PROVIDER_MODE=mock` until DGX-spark is reachable
- Live DGX preflight stays opt-in with `NEX_MO_LIVE_PREFLIGHT=1`; it is not
  part of the default regression gate.

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /internal/v1/auth/service-claim`
- `GET /api/v1/provider-routes`
- `GET /api/v1/provider-profiles`
- `POST /api/v1/embeddings`
- `POST /api/v1/rerank`
- `POST /api/v1/generations`

Manual live preflight:

```bash
NEX_MO_LIVE_PREFLIGHT=1 ./.venv/bin/python scripts/smoke/run_dgx_live_provider_preflight.py --summary
```

Configure `NEX_MO_LIVE_EMBEDDING_HEALTH_URL`,
`NEX_MO_LIVE_RERANKER_HEALTH_URL`, and `NEX_MO_LIVE_VLLM_MODELS_URL` in
`.env.local` or the shell before running live checks.
