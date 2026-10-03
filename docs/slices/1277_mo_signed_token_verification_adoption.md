# Slice 1277: MO signed-token verification adoption

## Goal

Adopt the shared signed service-token admission runtime across NeX-MO while
preserving the explicit admin-user path of the MVP acceptance endpoint.

## Implementation

- Wired the MO application to an audience-bound shared admission runtime.
- Routed provider, readiness, operations, catalog, and observability APIs
  through the central signed-token guard.
- Stored privacy-safe admitted claims in request state so catalog lifecycle
  actor lineage reuses the verified subject.
- Replaced the MVP acceptance service-token validator while preserving its
  admin user-token path. Failed signed tokens cannot fall through as users.
- Removed direct MO calls to the legacy service-token validator.

No database migration, outbound service token, or DGX provider is required.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-mo \
  --test tests/test_nex_mo_service_token_adoption.py \
  --test tests/test_mo_signed_token_adoption_smoke.py \
  --coverage-target scripts/smoke/run_mo_signed_token_adoption.py \
  --smoke scripts/smoke/run_mo_signed_token_adoption.py
```
