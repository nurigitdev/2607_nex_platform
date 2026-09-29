# Slice 1118: MO provider registry composition decoupling

## Goal

Remove the remote-runtime dependency on the provider API composition module by
extracting shared route and error contracts into a neutral registry boundary.

## Result

- `nex_mo.provider_registry` owns route values, route errors, default routes,
  filtering, and resolution.
- `nex_mo.providers` preserves all established registry exports for callers.
- `nex_mo.remote_provider`, transport, normalization, and telemetry depend on
  the neutral registry rather than the API composition module.
- Remote runtime no longer imports `nex_mo.providers`; the bidirectional import
  pressure identified in S111 is removed.
- Mock routes and all status/error behaviors remain unchanged.
- No table, migration, or provider request is introduced.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_registry_decoupling.py \
  tests/test_nex_mo_providers.py \
  tests/test_nex_mo_remote_provider.py \
  --cov=nex_mo.provider_registry \
  --cov=run_mo_provider_registry_decoupling \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_registry_decoupling.py --summary
```
