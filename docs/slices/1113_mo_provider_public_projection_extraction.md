# Slice 1113: MO provider public projection extraction

## Goal

Move provider route and model-profile wire projection into a privacy-safe module
without changing existing response shapes or `to_wire()` compatibility.

## Result

- Route and model-profile projection now live in `nex_mo.provider_projection`.
- Existing immutable value objects and their `to_wire()` entry points remain
  compatible.
- Optional embedding dimensions remain present only for embedding routes.
- Model paths, health environment names, endpoints, credentials, and process
  details cannot enter the public projection by generic object serialization.
- No table, migration, provider request, or live environment is required.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_projection.py \
  --cov=nex_mo.provider_projection \
  --cov=run_mo_provider_projection_extraction \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_projection_extraction.py --summary
```
