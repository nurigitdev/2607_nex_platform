# Slice 0066 Compatible Provider DGX Live Smoke

Status: Implemented.

Backlog candidate: `S6-016` Direct vLLM compatible provider DGX live smoke and
BF16 serving evidence policy.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0066 adds a protected live smoke runner for direct vLLM embedding and
reranker providers. The runner checks both provider endpoints without writing
endpoint URLs or API keys into saved evidence:

- embedding `GET /v1/models`
- embedding `POST /v1/embeddings`
- reranker `GET /v1/models`
- reranker `POST /v1/rerank`

Embedding responses are validated against the OpenAI-compatible response
contract. Reranker responses may use vLLM native `relevance_score` shape, so the
smoke runner normalizes the response in-memory before validating the NeX
compatible rerank response contract.

vLLM's OpenAI-compatible HTTP API does not expose loaded parameter dtype.
Therefore BF16 evidence is an out-of-band operator check: inspect vLLM launch
args or logs and confirm embedding/reranker processes run with BF16. The smoke
evidence records this explicitly instead of pretending HTTP can prove dtype.

## DGX Execution Policy

Current direct vLLM provider ports are:

- embedding: `9112`, model `Qwen3-Embedding-4B`
- reranking: `9113`, model `Qwen3-Reranker-0.6B`

Existing NeX-PCX providers, if still running, should stay on their existing
ports. Do not replace them during this smoke.

The model files remain on DGX-Spark under:

```text
/home/nexpcx/2608_nex_platform/models
```

Local regression still uses mock provider tests. DGX smoke is opt-in through
`NEX_COMPAT_LIVE_SMOKE=1`.

## Evidence

```bash
./.venv/bin/pytest tests/test_compatible_provider_live_smoke.py tests/test_nex_compatible_provider_app.py
scripts/quality/run_quality_gate.sh
```

Live evidence, when executed, should be written under `reports/live/`, which is
ignored by git.
