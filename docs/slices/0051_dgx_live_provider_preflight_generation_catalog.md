# Slice 0051 DGX Live Provider Preflight And Generation Catalog

Status: Implemented.

Backlog candidate: `S6-001` DGX live provider preflight and pluggable generation
model catalog.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`CONTRACT-MO-001`, `PLAT-FR-007`.

## Scope

Slice 0051 prepares live DGX-Spark provider verification without making DGX a
default regression dependency:

- MO model profiles now expose generation candidates:
  - `qwen3_5_122b_a10b_nvfp4` for `Qwen3.5-122B-A10B-NVFP4`.
  - `qwen3_6_27b_nvfp4` for `Qwen3.6-27B-NVFP4`.
  - `k_ai_generation_candidate` for domestic K-AI evaluation.
- Embedding and reranker defaults remain `Qwen3-embedding-4B` BF16 and
  `Qwen3-reranker-4B` BF16.
- `NEX_MO_GENERATION_PROFILE` selects exactly one generation profile, including
  operator-defined custom profiles.
- `model_profile.v1` supports candidate role, selection reason, live health env
  name, `remote_http` runtime, and planned model status.
- `scripts/smoke/run_dgx_live_provider_preflight.py` checks configured live
  embedding, reranker, and vLLM endpoints only when `NEX_MO_LIVE_PREFLIGHT=1`.
- The live preflight output avoids printing endpoint URLs or response bodies.

The default quality gate remains mock-first. Live DGX evidence should be run
manually or as a protected release/nightly check.

## Files

- `services/nex-mo/nex_mo/providers.py`
- `contracts/schemas/service/nex_mo/model_profile.v1.schema.json`
- `contracts/examples/generation/mo_model_profile.generation_qwen35_selected.json`
- `contracts/examples/generation/mo_model_profile.generation_kai_planned.json`
- `scripts/smoke/run_dgx_live_provider_preflight.py`
- `tests/test_nex_mo_providers.py`
- `tests/test_dgx_live_provider_preflight.py`
- `.env.example`
- `services/nex-mo/README.md`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_nex_mo_providers.py tests/test_dgx_live_provider_preflight.py tests/test_contract_validation.py
scripts/quality/run_quality_gate.sh
./.venv/bin/python scripts/smoke/run_dgx_live_provider_preflight.py --summary
```

The last command should print skipped status unless live DGX env vars are
explicitly enabled.
