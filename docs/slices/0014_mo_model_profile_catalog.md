# Slice 0014 MO Model Profile Catalog

Status: Implemented.

Backlog candidate: `S2-004` MO embedding/reranker/generation profile
configuration surface.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`CONTRACT-MO-001`.

## Scope

Slice 0014 adds a model profile catalog to MO:

- `GET /api/v1/provider-profiles` lists selected profiles by capability.
- Optional `capability` query filters embedding, reranking, or generation.
- Defaults match the PCX lessons that will carry into NeX:
  - Embedding: `qwen3_embedding_4b_bf16`
  - Reranker: `qwen3_reranker_0_6b_bf16`
  - Generation: `qwen3_5_122b_a10b_nvfp4`
- Model paths default under `/data/nex-platform/models`.
- `NEX_MO_PROVIDER_MODE=mock` remains the default until DGX-spark is reachable.

Slice 0061 updated the reranker default to the DGX-Spark runtime target
`Qwen3-Reranker-0.6B`. The previous 4B reranker remains planning provenance,
not the current selected default.

The catalog is separate from provider routes. Routes answer "which alias can
serve a request"; profiles answer "which model/runtime profile is selected for
that capability".

## Contract Artifacts

- `contracts/schemas/service/nex_mo/model_profile.v1.schema.json`
- `contracts/examples/generation/mo_model_profile.embedding_qwen3.json`
- `contracts/tests/negative/generation/mo_model_profile.api_key_leak.json`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover default Qwen values, environment overrides, profile
filtering, endpoint authentication, and rejection of secret-bearing profile
payloads in contract fixtures.
