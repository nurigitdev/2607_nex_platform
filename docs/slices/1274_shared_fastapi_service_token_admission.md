# Slice 1274: Shared FastAPI service-token admission runtime

## Goal

Add one shared request-admission boundary for local signed-token verification,
controlled mock compatibility, and revocation-sensitive OA introspection.

## Implementation

- Added bounded HTTP clients for OA JWKS and token introspection. Both use a
  fixed configured OA base URL, a three-second default timeout, privacy-safe
  errors, and no token-directed remote key locations.
- Added `TEST_MOCK`, `DUAL_READ`, and `SIGNED_ONLY` request admission. DUAL_READ
  requires an explicit legacy caller allowlist and epoch deadline; it never
  retries a failed signed token as a mock token.
- Added route classes. READ uses local signature/claim verification, while
  WRITE, ADMIN, CREDENTIAL, and KEY_MANAGEMENT require active OA introspection.
- Added strict introspection binding across subject, audience, scope, service,
  credential lineage, time claims, and SHA-256 token-id digest.
- Added optional admission injection to the shared FastAPI service shell. The
  default remains unchanged until each consumer's dedicated adoption Slice.
- Extended OA introspection v1 with `token_id_digest`. Raw token and raw `jti`
  values remain forbidden from response projections.

## Configuration

- `NEX_SERVICE_TOKEN_ROLLOUT_PROFILE`
- `NEX_OA_BASE_URL`
- `NEX_OA_AUTH_TIMEOUT_SECONDS`
- `NEX_OA_INTROSPECTION_SERVICE_TOKEN`
- `NEX_LEGACY_MOCK_CALLERS`
- `NEX_MOCK_COMPATIBILITY_DEADLINE_EPOCH`

No database migration or DGX model provider is required.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-runtime \
  --test tests/test_platform_service_token_admission_smoke.py \
  --test tests/test_nex_oa_token_validation_service.py \
  --test tests/test_nex_oa_signed_token_api.py \
  --test tests/test_generation_compatibility.py \
  --test tests/test_prompt_registry.py \
  --test tests/test_generation_recovery_policy.py \
  --test tests/test_nex_cx_retrieval.py \
  --test tests/test_platform_signed_token_adoption_boundary.py \
  --coverage-target services/_shared/nex_runtime/service_token_admission.py \
  --coverage-target services/nex-oa/nex_oa/token_validation_service.py \
  --coverage-target scripts/smoke/run_platform_service_token_admission.py \
  --smoke scripts/smoke/run_platform_service_token_admission.py
```
