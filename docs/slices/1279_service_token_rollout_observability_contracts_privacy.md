# Slice 1279: Service-token rollout observability, contracts, and privacy

## Goal

Make signed service-token rollout state observable with one protected,
contracted, privacy-safe projection across all platform consumers.

## Implementation

- Added thread-safe accepted mock, accepted signed, rejected, and introspected
  counters to the shared admission runtime.
- Added bounded JWKS cache metadata without key IDs, key material, source URLs,
  tokens, credentials, or raw errors.
- Added a protected `/internal/v1/auth/service-token-runtime` route to services
  using the shared admission runtime.
- Added positive and negative JSON contract fixtures. Unknown fields such as a
  raw `access_token` fail schema validation.
- Added repository evidence proving AE, CX, MO, and AG use the same runtime.

No database migration or DGX provider is required.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-cx \
  --test tests/test_nex_runtime_service_token_admission.py \
  --test tests/test_nex_runtime_signed_token_verifier.py \
  --test tests/test_service_token_rollout_observability_smoke.py \
  --coverage-target services/_shared/nex_runtime/service_token_admission.py \
  --coverage-target services/_shared/nex_runtime/signed_token_verifier.py \
  --coverage-target scripts/smoke/run_service_token_rollout_observability.py \
  --smoke scripts/smoke/run_service_token_rollout_observability.py
```
