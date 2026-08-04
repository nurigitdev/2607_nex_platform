# Slice 0061 Local Live Provider Config Guard

Status: Implemented.

Backlog candidate: `S6-011` Local live provider config guard and Qwen3
reranker 0.6B update.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0061 reflects the current DGX-Spark remote reranker runtime and adds a
network-free guard before protected live smoke tests:

- MO reranker defaults now select `qwen3_reranker_0_6b_bf16` and
  `Qwen3-Reranker-0.6B`.
- `.env.example` live reranker model and expected-model defaults are aligned to
  `Qwen3-Reranker-0.6B`.
- `scripts/smoke/check_local_live_provider_config.py` builds a redacted local
  snapshot of provider execution configs, live preflight expected models, and
  selected model profiles.
- The guard reports `SKIPPED` unless `NEX_MO_PROVIDER_MODE=live`.
- In live mode, it fails fast when required endpoints are not configured, when
  timeout parsing is invalid, or when execution model names disagree with live
  preflight expected model names.
- The snapshot excludes endpoint URLs, API keys, and model paths.

The guard does not call DGX-Spark. It is intended to run before
`run_dgx_live_provider_preflight.py`, so operator-side configuration mistakes
can be caught without touching remote providers.

## Files

- `services/nex-mo/nex_mo/providers.py`
- `services/nex-mo/nex_mo/remote_provider.py`
- `scripts/smoke/check_local_live_provider_config.py`
- `tests/test_local_live_provider_config.py`
- `tests/test_nex_mo_providers.py`
- `tests/test_nex_mo_remote_provider.py`
- `tests/test_dgx_live_provider_preflight.py`
- `.env.example`
- `services/nex-mo/README.md`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_local_live_provider_config.py tests/test_nex_mo_providers.py tests/test_nex_mo_remote_provider.py tests/test_dgx_live_provider_preflight.py
./.venv/bin/python scripts/smoke/check_local_live_provider_config.py --summary
scripts/quality/run_quality_gate.sh
```

The summary command should print skipped status unless
`NEX_MO_PROVIDER_MODE=live` is explicitly set.
