# Slice 0295: Protected Live RAG PostgreSQL Smoke

## Scope

Add a guarded smoke runner that proves the protected live RAG flow can use the
real CX test database and all three OpenAI-compatible DGX providers in one
execution.

Default regression stays deterministic and network-free. The live path is
opt-in and restricted to the `test` profile.

## Implemented

- Added `scripts/smoke/run_protected_live_rag_postgres_smoke.py`.
- The smoke runs the CX API flow for upload, extraction, chunking, lexical
  index, embedding index, retrieval reranking, and grounded generation.
- CX content/retrieval storage uses `SqlAlchemyCxContentRepository` against the
  configured `nex_cx_test` URL.
- Provider calls still flow through the MO service API, with MO in live remote
  mode for embedding, reranking, and generation.
- Evidence directly reads PostgreSQL tables for source file, content object,
  extraction artifact, chunk set, chunks, lexical index rows, chunk embeddings,
  retrieval package status, rerank state, evidence count, and persisted score.
- The smoke request sets `low_confidence_threshold=0.0` only for this evidence
  run, so provider score calibration cannot block generation when reranker
  wiring, persistence, and telemetry are otherwise healthy.
- Cleanup removes the smoke retrieval package and document-derived CX rows.
- Evidence excludes provider endpoints, API keys, database passwords, source
  text, and local storage paths.

## Live Test Command

```bash
NEX_PROTECTED_LIVE_RAG_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:<password>@127.0.0.1:5432/nex_cx_test' \
NEX_MO_REMOTE_EMBEDDING_URL='http://192.168.20.243:9112/v1/embeddings' \
NEX_MO_REMOTE_EMBEDDING_API_KEY='<api-key>' \
NEX_MO_REMOTE_EMBEDDING_MODEL='Qwen3-Embedding-4B' \
NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS='Qwen3-Embedding-4B' \
NEX_MO_REMOTE_RERANKER_URL='http://192.168.20.243:9113/v1/rerank' \
NEX_MO_REMOTE_RERANKER_API_KEY='<api-key>' \
NEX_MO_REMOTE_RERANKER_MODEL='Qwen3-Reranker-0.6B' \
NEX_MO_LIVE_EXPECTED_RERANKER_MODELS='Qwen3-Reranker-0.6B' \
NEX_MO_VLLM_BASE_URL='http://192.168.20.243:12000' \
NEX_MO_VLLM_API_KEY='<api-key>' \
NEX_MO_VLLM_MODEL='Qwen3.5-122B-A10B-NVFP4' \
NEX_MO_LIVE_EXPECTED_GENERATION_MODELS='Qwen3.5-122B-A10B-NVFP4' \
./.venv/bin/python scripts/smoke/run_protected_live_rag_postgres_smoke.py --summary
```

Expected summary shape:

```text
protected_live_rag_postgres_smoke=pass service=nex-cx profile=test db_env=NEX_CX_TEST_DATABASE_URL retrieval=READY rerank=APPLIED generation=COMPLETED embedding_dim=2560
```

## Evidence

- Python regression:
  `./.venv/bin/pytest tests/test_protected_live_rag_postgres_smoke.py -q`
- Protected live RAG PostgreSQL smoke:
  `./.venv/bin/python scripts/smoke/run_protected_live_rag_postgres_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
