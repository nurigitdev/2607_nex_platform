# nex-mo

NeX Model Operations service.

Owned database env: `NEX_MO_DATABASE_URL`.

Model profile defaults:

- Model root: `NEX_MO_MODEL_ROOT` or `/data/nex-platform/models`
- Embedding: `qwen3_embedding_4b_bf16` at `qwen3-embedding-4b-bf16`
- Reranker: `qwen3_reranker_4b_bf16` at `qwen3-reranker-4b-bf16`
- Generation: `qwen3_6_27b_nvfp4` at `qwen3.6-27b-nvfp4`
- Provider mode: `NEX_MO_PROVIDER_MODE=mock` until DGX-spark is reachable

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
