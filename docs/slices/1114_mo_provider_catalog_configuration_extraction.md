# Slice 1114: MO provider catalog and configuration extraction

## Goal

Move model-profile catalog construction and environment resolution out of the
provider API/runtime module while retaining the established import contract.

## Result

- `nex_mo.provider_catalog` now owns model profiles, generation candidates,
  selection status, private model paths, and related environment resolution.
- `nex_mo.providers` preserves compatibility exports and its existing
  `build_model_profile_catalog()` entry point.
- S111 catalog drift probes now follow their evidence to the owning module.
- Runtime-coupling LOC evidence measures the extracted module family instead
  of treating a file move as disappearance of responsibility.
- Public projection remains path-free and no table or migration is added.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_catalog_extraction.py \
  tests/test_nex_mo_providers.py \
  --cov=nex_mo.provider_catalog \
  --cov=run_mo_provider_catalog_extraction \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_catalog_extraction.py --summary
```
