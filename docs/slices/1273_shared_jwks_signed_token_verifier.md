# Slice 1273: Shared JWKS signed-token verifier foundation

## Goal

Provide the platform-owned local verifier that accepts NeX-OA `service_access`
tokens without importing OA service internals or reading the OA database.

## Implementation

- Added `nex_runtime.signed_token_verifier` with strict RS256 compact-JWT
  parsing, duplicate-member rejection, signature verification, and S125/S127
  service claim validation.
- Added a bounded JWKS cache with a five-minute TTL, at most 16 keys, one
  forced refresh for an unknown `kid`, and fail-closed refresh behavior.
- Restricted public keys to RSA signing JWKs with a minimum 3072-bit modulus.
  Private JWK members and token-directed remote-key headers are rejected.
- Returned a typed privacy-safe claims projection. Raw tokens and raw `jti`
  values are never returned; only the SHA-256 token-id digest is retained.
- Kept OA revocation and credential-state introspection outside the local
  verifier. Route-sensitive introspection belongs to the Slice 1274 admission
  runtime.

## Boundaries

- This Slice defines the JWKS source protocol and deterministic static source.
  The bounded OA HTTP source and FastAPI admission dependency arrive in Slice
  1274.
- This Slice supports only `service_access`; delegated user tokens remain
  deferred by the S128 boundary.
- No database migration and no DGX provider are required.

## Verification

The smoke path creates a real S127 OA service principal and credential, issues
an RS256 token through the OA client-credential exchange, and verifies it only
through the shared public-JWKS runtime.

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-runtime \
  --test tests/test_nex_runtime_signed_token_verifier.py \
  --test tests/test_platform_signed_token_verifier_smoke.py \
  --test tests/test_generation_compatibility.py \
  --test tests/test_prompt_registry.py \
  --test tests/test_generation_recovery_policy.py \
  --test tests/test_nex_cx_retrieval.py \
  --test tests/test_platform_signed_token_adoption_boundary.py \
  --coverage-target services/_shared/nex_runtime/signed_token_verifier.py \
  --coverage-target scripts/smoke/run_platform_signed_token_verifier.py \
  --smoke scripts/smoke/run_platform_signed_token_verifier.py
```
