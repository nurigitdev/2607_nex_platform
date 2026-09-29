# Slice 1104: MO provider catalog and configuration drift audit

## Goal

Re-baseline the active MO model catalog, provider request shapes, timeout
profiles, public metadata, and deprecated configuration surface.

## Result

- All three capabilities have a selected default and use direct vLLM-compatible
  request shapes: `openai_embeddings`, `rerank`, and `openai_models`.
- Current models are Qwen3 Embedding 4B, Qwen3 Reranker 4B, and Qwen3.5 4B.
- Six classified drift findings remain: embedding model-name casing, two live
  profiles with `mock-*` aliases, legacy health-env projection, unvalidated
  provider mode, and public internal model-path projection.
- The model-path projection is the single high-risk finding and is assigned to
  Slice 1106. Canonical naming is repaired with it.
- Stable alias redesign and strict provider-mode migration remain ordered S112
  work because they alter client-visible routing semantics.
- No provider endpoint, credential, or raw request payload is emitted by the
  audit evidence.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_mo_catalog_config_drift_audit.py --summary

./.venv/bin/pytest -q \
  tests/test_mo_catalog_config_drift_audit.py \
  --cov=nex_mo.catalog_config_audit \
  --cov=run_mo_catalog_config_drift_audit \
  --cov-branch --cov-report=term-missing
```
