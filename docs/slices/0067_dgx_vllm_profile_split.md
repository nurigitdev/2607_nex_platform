# Slice 0067 DGX vLLM Profile Split

Status: Implemented.

Backlog candidate: `S6-017` Protected DGX vLLM profile and legacy PCX profile
split.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0067 makes direct vLLM serving the canonical protected DGX profile while
keeping the older NeX-PCX provider request shapes available under an explicit
legacy profile.

Supported protected profile names:

- `dgx_vllm`: canonical profile. Embedding uses `openai_embeddings`, reranking
  uses `rerank`, and generation uses vLLM OpenAI-compatible APIs.
- `dgx`: deprecated alias for `dgx_vllm`.
- `dgx_pcx_legacy`: legacy compatibility profile. Embedding uses
  `nex_pcx_embeddings_v1`; reranking uses `nex_pcx_rerank_v1`.

The protected profile evidence now records both `requested_profile` and
`resolved_profile` so operators can see whether an alias was used.

## Evidence

```bash
./.venv/bin/pytest tests/test_protected_dgx_live_profile.py tests/test_local_live_provider_config.py tests/test_dgx_live_provider_preflight.py
scripts/quality/run_quality_gate.sh
```
