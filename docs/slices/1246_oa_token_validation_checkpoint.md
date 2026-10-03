# Slice 1246: OA validation, JWKS, and revocation checkpoint

## Goal

Freeze fail-closed local validation, JWKS caching, live introspection, and
revocation semantics, then run the S125 fifth-Slice Checkpoint Gate.

## Decision

- Every signed access token is checked locally for algorithm, `kid` and
  signature, type, issuer, audience, token use, time bounds, and required
  scope. Raw access tokens are never logged.
- JWKS cache TTL is 300 seconds. An unknown `kid` or expired cache triggers at
  most one synchronous refresh; a failed refresh never permits stale-key
  acceptance.
- `READ` routes may use fresh local verification without introspection.
  `WRITE`, `ADMIN`, `CREDENTIAL`, and `KEY_MANAGEMENT` routes additionally
  require live OA introspection with a three-second timeout.
- Introspection binds active state, issuer, audience, subject, token use,
  `jti`, and credential or authorization revision. Inactive tokens return
  `401`; missing scope returns `403`; an unavailable required trust dependency
  returns `503`. Network failure never becomes authentication success.
- This is a policy checkpoint, not a signed-token runtime activation. Existing
  mock compatibility remains unchanged until S126.

## Verification

```bash
./scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_oa_token_validation_policy.py \
  --test tests/test_oa_token_validation_checkpoint.py \
  --coverage-target services/nex-oa/nex_oa/token_validation_policy.py \
  --coverage-target scripts/smoke/run_oa_token_validation_checkpoint.py \
  --smoke scripts/smoke/run_oa_token_validation_checkpoint.py
```
