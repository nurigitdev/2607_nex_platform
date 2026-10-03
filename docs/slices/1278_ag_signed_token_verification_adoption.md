# Slice 1278: AG signed-token verification adoption

## Goal

Adopt the shared signed service-token runtime across NeX-AG inbound APIs and
outbound platform clients without weakening operator user-token authorization.

## Implementation

- Added one AG authentication module for request admission, verified claim
  state, operator admin fallback, and profile-driven outbound tokens.
- Wired the AG application to the audience-bound shared admission runtime.
- Replaced duplicated legacy validators across AG operational APIs.
- Preserved the explicit admin user-token path for MVP, audit, retention, and
  operator review endpoints. Failed service tokens cannot fall through as users.
- Removed silent per-client mock fallbacks. `TEST_MOCK` remains explicit, while
  `DUAL_READ` and `SIGNED_ONLY` require configured signed outbound tokens.

No database migration or DGX provider is required.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-ag \
  --test tests/test_nex_ag_service_token_adoption.py \
  --test tests/test_ag_signed_token_adoption_smoke.py \
  --coverage-target services/nex-ag/nex_ag/service_auth.py \
  --coverage-target scripts/smoke/run_ag_signed_token_adoption.py \
  --smoke scripts/smoke/run_ag_signed_token_adoption.py
```
