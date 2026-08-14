# Slice 0293: CX Processing Pipeline Remote Embedding PostgreSQL Smoke

## Scope

Extend the protected CX real-document processing PostgreSQL smoke so it can
prove the full PDF/DOCX/PPTX/XLSX processing path against `nex_cx_test` while
using the live OpenAI-compatible DGX embedding provider.

Default regression remains network-free and deterministic. Remote embedding is
enabled only by an explicit smoke flag.

## Implemented

- Added optional remote embedding mode to
  `scripts/smoke/run_cx_real_document_processing_pipeline_postgres_smoke.py`.
- `NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_REMOTE_EMBEDDING=1` switches the
  smoke from the static embedding client to the canonical `dgx_vllm`
  OpenAI-compatible embedding adapter.
- Remote mode validates only the embedding settings required by the CX
  processing smoke:
  - `NEX_MO_REMOTE_EMBEDDING_URL` is configured;
  - request shape is `openai_embeddings`;
  - selected model is listed in `NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS`;
  - timeout values are valid.
- PostgreSQL observations now include chunk and summary embedding vector
  dimensions, and the smoke checks them against
  `NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_REMOTE_EMBEDDING_EXPECTED_DIMENSION`
  in remote mode.
- Evidence records safe provider metadata only: mode, configured flags, model
  names, request shape, call counts, and vector dimension. Provider URLs,
  API keys, source text, Markdown paths, and raw vectors remain excluded.
- Regression tests cover static mode, fake remote OpenAI-compatible embedding
  calls, config-guard failures, provider error mapping, and dimension checks.

## Live Test Command

```bash
NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_POSTGRES_SMOKE=1 \
NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_REMOTE_EMBEDDING=1 \
NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_REMOTE_EMBEDDING_EXPECTED_DIMENSION=2560 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:nuri1004@127.0.0.1:5432/nex_cx_test' \
NEX_MO_REMOTE_EMBEDDING_URL='http://192.168.20.243:9112/v1/embeddings' \
NEX_MO_REMOTE_EMBEDDING_API_KEY='<api-key>' \
NEX_MO_REMOTE_EMBEDDING_MODEL='Qwen3-Embedding-4B' \
NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS='Qwen3-Embedding-4B' \
./.venv/bin/python scripts/smoke/run_cx_real_document_processing_pipeline_postgres_smoke.py --summary
```

Expected summary shape:

```text
cx_real_document_processing_pipeline_postgres_smoke=pass profile=test db_env=NEX_CX_TEST_DATABASE_URL formats=4 embedding_mode=remote_openai_compatible pipeline_runs=4 chunks=4 embedding_dim=2560
```

## Evidence

- Python regression:
  `./.venv/bin/pytest tests/test_cx_real_document_processing_pipeline_postgres_smoke.py -q`
- Protected remote embedding PostgreSQL smoke:
  `./.venv/bin/python scripts/smoke/run_cx_real_document_processing_pipeline_postgres_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
