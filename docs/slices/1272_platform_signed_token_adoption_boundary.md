# Slice 1272: Platform-wide signed-token verification adoption boundary

## Goal

Freeze the S128 consumer-verification and rollout boundary before replacing
the platform's mock-only service-token validator.

## Decision

- NeX-OA remains the `urn:nex-platform:oa` issuer and owns token exchange,
  JWKS, introspection, signing-key metadata, and revocation state.
- `nex-runtime` owns the shared RS256 verifier. Consumer order remains
  `nex-ae-api -> nex-cx -> nex-mo -> nex-ag` after the shared verifier and OA
  issuer are ready.
- Local JWKS signature and claim validation is the primary request path.
  Revocation-sensitive operations use bounded OA introspection; consumers
  never read the OA database directly.
- Rollout remains forward-only: `TEST_MOCK -> DUAL_READ -> SIGNED_ONLY`.
  Silent outbound mock fallback is forbidden in every profile. DUAL_READ mock
  admission requires an explicit caller allowlist and removal deadline.
- S128 adopts only `service_access`. `delegated_user_access` remains deferred.
- S128 creates no database table and does not require DGX model providers.
  Actual `nex_oa_test` evidence is required in Slice 1280.

## Slice Order

1. 1272 boundary audit and refactoring checkpoint
2. 1273 shared JWKS verifier foundation
3. 1274 shared FastAPI admission runtime
4. 1275 AE signed-token verification adoption
5. 1276 CX adoption and Checkpoint Gate
6. 1277 MO signed-token verification adoption
7. 1278 AG signed-token verification adoption
8. 1279 rollout observability, contracts, and privacy hardening
9. 1280 local platform loopback and actual PostgreSQL smoke
10. 1281 S128 closure and Full Gate

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --test tests/test_platform_signed_token_adoption_boundary.py \
  --coverage-target services/_shared/nex_runtime/signed_token_adoption_boundary.py \
  --coverage-target scripts/smoke/run_platform_signed_token_adoption_boundary.py \
  --smoke scripts/smoke/run_platform_signed_token_adoption_boundary.py
```
