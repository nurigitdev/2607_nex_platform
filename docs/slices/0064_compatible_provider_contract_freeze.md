# Slice 0064 Compatible Provider Contract Freeze

Status: Implemented.

Backlog candidate: `S6-014` OpenAI-compatible embedding and NeX-compatible
reranker provider contract freeze.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0064 freezes the canonical provider target for new nex-platform remote
providers:

- Embedding providers expose OpenAI-compatible `POST /v1/embeddings` with
  `model` and `input`.
- Reranker providers expose NeX-compatible `POST /v1/rerank` with `model`,
  `query`, `documents`, and optional `top_n`.
- Providers expose `GET /healthz` using
  `compatible_provider_health.v1`.
- Health reports include `requested_torch_dtype`, `loaded_parameter_dtype`, and
  `dtype_match`.
- BF16-required Qwen embedding/reranker providers must report
  `bfloat16` for both requested and loaded dtype. A BF16 model loaded as FP32 is
  a contract failure.
- Provider-private values such as model paths, endpoint URLs, API keys, tokens,
  or passwords are not part of request/response/evidence contracts.

Existing NeX-PCX provider shapes remain supported through Slice 0063 adapter
compatibility, but they are no longer the canonical target for new provider
source.

## Contract Artifacts

- `contracts/schemas/service/nex_mo/compatible_embedding_request.v1.schema.json`
- `contracts/schemas/service/nex_mo/compatible_embedding_response.v1.schema.json`
- `contracts/schemas/service/nex_mo/compatible_rerank_request.v1.schema.json`
- `contracts/schemas/service/nex_mo/compatible_rerank_response.v1.schema.json`
- `contracts/schemas/service/nex_mo/compatible_provider_health.v1.schema.json`
- `contracts/openapi/nex-compatible-providers.openapi.yaml`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_compatible_provider_contracts.py tests/test_contract_validation.py
./.venv/bin/python scripts/quality/validate_contracts.py
scripts/quality/run_quality_gate.sh
```

The BF16 regression case is represented by
`mo_compatible_provider_health.fp32_loaded_for_bf16.json`.
