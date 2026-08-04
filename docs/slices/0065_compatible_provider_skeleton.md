# Slice 0065 Compatible Provider Skeleton

Status: Implemented.

Backlog candidate: `S6-015` Mock-first compatible embedding/reranker provider
source skeleton.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0065 adds a provider-side FastAPI package for the canonical Slice 0064
contracts:

- `GET /healthz` emits `compatible_provider_health.v1`.
- `POST /v1/embeddings` accepts the OpenAI-compatible embedding shape.
- `POST /v1/rerank` accepts the NeX-compatible rerank shape.
- The default backend is `mock`, so local regression does not require DGX-Spark
  or local model files.
- Provider runtime paths remain process-local configuration and are not returned
  in health, response, or evidence payloads.

## BF16 Guard

The skeleton carries the dtype fields needed for DGX validation:

- `precision_policy`
- `requested_torch_dtype`
- `loaded_parameter_dtype`
- `dtype_match`

For local mock mode, these default to `mock_no_model` and `mock`. In a live
torch-backed DGX runtime, Qwen embedding/reranker providers must report
`bf16_required`, `bfloat16`, `bfloat16`, and `dtype_match=true`. If a BF16 model
is accidentally loaded as FP32, `/healthz` becomes degraded and contract
validation fails.

## Local Evidence

```bash
./.venv/bin/pytest tests/test_nex_compatible_provider_app.py tests/test_compatible_provider_contracts.py
scripts/quality/run_quality_gate.sh
```

The quality gate now includes `providers` in its coverage target.
