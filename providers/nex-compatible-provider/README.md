# NeX Compatible Provider

Status: Slice 0065 mock-first source skeleton.

This package is the canonical source target for new remote embedding and rerank
providers. It intentionally exposes the Slice 0064 compatible wire contracts:

- `GET /healthz`
- `POST /v1/embeddings`
- `POST /v1/rerank`

The default backend is `mock`, so local regression can run without DGX-Spark or
model files. DGX deployment should run separate embedding and reranking
processes with `NEX_COMPAT_PROVIDER_CAPABILITY=embedding` or
`NEX_COMPAT_PROVIDER_CAPABILITY=reranking`.

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
response, health, or evidence payloads. For the DGX-Spark host, set
`NEX_COMPAT_PROVIDER_MODEL_ROOT=/home/nexpcx/2608_nex_platform/models` in the
remote runtime environment.

Qwen embedding and reranker live backends must request BF16 and confirm the
loaded parameter dtype is BF16. If a BF16-required model loads as FP32,
`dtype_match` must become false and the live smoke must fail.
