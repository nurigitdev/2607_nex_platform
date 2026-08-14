# Slice 0291: Protected Remote Provider Live Smoke Evidence

## Scope

Add protected live smoke evidence for the actual remote model providers that
the current office/DGX environment exposes:

- OpenAI-compatible embedding provider;
- vLLM-compatible reranker provider;
- vLLM OpenAI-compatible chat-completions generation provider.

Slice 0290 proved the real-document CX pipeline against PostgreSQL, but it kept
model execution deterministic with local/static provider behavior. This slice
separates provider connectivity from default regression so live DGX availability
can be checked without making the normal quality gate network-dependent.

## Implemented

- Added `scripts/smoke/run_protected_remote_provider_live_smoke.py`.
- The smoke is guarded by
  `NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE=1` and skips by default.
- The smoke reuses the existing `NEX_MO_REMOTE_*` and `NEX_MO_VLLM_*` settings.
- It applies the canonical `dgx_vllm` defaults:
  - embedding request shape: `openai_embeddings`;
  - reranker request shape: `rerank`;
  - generation request shape: `openai_chat_completions`.
- It calls the same MO remote-provider execution adapters used by service code,
  so normalization, failure taxonomy, and telemetry are covered.
- Evidence records only safe observations:
  - embedding count and dimension;
  - reranker result count, top index, and top score;
  - generation finish reason, output length, and usage;
  - provider telemetry counters.
- Evidence redaction rejects provider endpoint URLs, API keys, raw smoke inputs,
  rerank documents, generation prompt/output text, and embedding vectors.
- Wired the skipped-by-default smoke into the full quality gate.

## Live Test Command

```bash
NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE=1 \
NEX_MO_REMOTE_EMBEDDING_URL='http://192.168.20.243:9112/v1/embeddings' \
NEX_MO_REMOTE_EMBEDDING_API_KEY='<api-key>' \
NEX_MO_REMOTE_RERANKER_URL='http://192.168.20.243:9113/v1/rerank' \
NEX_MO_REMOTE_RERANKER_API_KEY='<api-key>' \
NEX_MO_VLLM_BASE_URL='http://192.168.20.243:12000' \
NEX_MO_VLLM_API_KEY='<api-key>' \
./.venv/bin/python scripts/smoke/run_protected_remote_provider_live_smoke.py --summary
```

## Evidence

- Protected live smoke:
  `./.venv/bin/python scripts/smoke/run_protected_remote_provider_live_smoke.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_protected_remote_provider_live_smoke.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

## Follow-Up

Slice 0293 should connect the CX real-document processing smoke to remote
embedding execution. Reranker and generation live behavior should stay in
retrieval/RAG and summary-generation slices rather than being implied by the
document-processing pipeline smoke.
