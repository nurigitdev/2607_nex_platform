# Slice 0294: CX Retrieval Remote Reranker PostgreSQL Smoke

## Scope

Extend the CX retrieval package PostgreSQL smoke so it can persist retrieval
evidence scored by the live OpenAI-compatible DGX reranker against
`nex_cx_test`.

Default regression stays deterministic and network-free. Remote reranker mode
is opt-in.

## Implemented

- Added `NEX_CX_RETRIEVAL_POSTGRES_REMOTE_RERANKER=1` to
  `scripts/smoke/run_cx_retrieval_postgres_smoke.py`.
- Remote mode applies the canonical `dgx_vllm` reranker defaults and validates:
  - `NEX_MO_REMOTE_RERANKER_URL` is configured;
  - request shape is `rerank`;
  - selected model is listed in `NEX_MO_LIVE_EXPECTED_RERANKER_MODELS`;
  - timeout values are valid.
- The smoke calls the MO remote reranker adapter, persists
  `rerank_state=APPLIED`, and stores the live top rerank score as the
  retrieval evidence `final_score`.
- Evidence reports safe reranker metadata only: mode, state, model names,
  request shape, result count, top index, and top score. Provider URLs, API
  keys, query text, evidence text, and source text are excluded.
- Regression tests cover static mode, fake OpenAI-compatible reranker mode,
  config-guard failures, redaction, and PostgreSQL cleanup behavior.

## Live Test Command

```bash
NEX_CX_RETRIEVAL_POSTGRES_SMOKE=1 \
NEX_CX_RETRIEVAL_POSTGRES_REMOTE_RERANKER=1 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:nuri1004@127.0.0.1:5432/nex_cx_test' \
NEX_MO_REMOTE_RERANKER_URL='http://192.168.20.243:9113/v1/rerank' \
NEX_MO_REMOTE_RERANKER_API_KEY='<api-key>' \
NEX_MO_REMOTE_RERANKER_MODEL='Qwen3-Reranker-0.6B' \
NEX_MO_LIVE_EXPECTED_RERANKER_MODELS='Qwen3-Reranker-0.6B' \
./.venv/bin/python scripts/smoke/run_cx_retrieval_postgres_smoke.py --summary
```

Expected summary shape:

```text
cx_retrieval_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL rerank=APPLIED
```

## Evidence

- Python regression:
  `./.venv/bin/pytest tests/test_smoke_helpers.py -q`
- Protected remote reranker PostgreSQL smoke:
  `./.venv/bin/python scripts/smoke/run_cx_retrieval_postgres_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
