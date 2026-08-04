# NeX Compatible Provider

Status: Slice 0065 mock-first source skeleton.

This package is the local mock contract harness for compatible embedding and
rerank providers. It intentionally exposes the Slice 0064 compatible wire
contracts:

- `GET /healthz`
- `POST /v1/embeddings`
- `POST /v1/rerank`

The default backend is `mock`, so local regression can run without DGX-Spark or
model files. Production DGX serving uses direct vLLM endpoints for embedding
and reranking instead of this FastAPI harness.

## Local Mock Run

```bash
PYTHONPATH=providers/nex-compatible-provider \
NEX_COMPAT_PROVIDER_CAPABILITY=embedding \
NEX_COMPAT_PROVIDER_BACKEND=mock \
uvicorn nex_compatible_provider.app:app --host 127.0.0.1 --port 9113
```

```bash
PYTHONPATH=providers/nex-compatible-provider \
NEX_COMPAT_PROVIDER_CAPABILITY=reranking \
NEX_COMPAT_PROVIDER_BACKEND=mock \
uvicorn nex_compatible_provider.app:app --host 127.0.0.1 --port 9114
```

## DGX Notes

Model paths stay provider-private and must not be returned by request,
response, health, or evidence payloads. The DGX vLLM model root stays in remote
process configuration.

Qwen embedding and reranker vLLM processes must request BF16. Because vLLM's
OpenAI-compatible HTTP API does not expose loaded parameter dtype, BF16 evidence
is collected by inspecting vLLM launch args or logs rather than by adding a
provider adapter.

## Protected Live Smoke

After starting direct vLLM embedding and reranker providers, run:

```bash
NEX_COMPAT_LIVE_SMOKE=1 \
NEX_COMPAT_EMBEDDING_URL=http://<host>:9112/v1/embeddings \
NEX_COMPAT_RERANKER_URL=http://<host>:9113/v1/rerank \
./.venv/bin/python scripts/smoke/run_compatible_provider_live_smoke.py --summary
```

The evidence writer redacts endpoint and credential values before saving JSON.
