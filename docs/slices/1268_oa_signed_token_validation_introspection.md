# Slice 1268: OA signed-token validation and introspection runtime

## Outcome

- Added strict compact-JWT parsing, duplicate JSON-member rejection, RS256
  signature verification, and 3072-bit public-JWK validation.
- Runtime validation enforces issuer/profile shape, clock skew, expiration,
  audience, required scopes, JTI revocation, credential status/revision, active
  principal identity, and current principal audience/scope allowlists.
- Added a bounded introspection projection. Inactive responses expose only a
  stable reason code; active responses exclude the raw token and JTI.
- Credential rotation, principal disablement, and permission removal take
  effect without waiting for the five-minute token lifetime to expire.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_token_validation_service.py \
  --test tests/test_nex_oa_service_principal_service.py \
  --test tests/test_oa_token_validation_smoke.py \
  --coverage-target services/nex-oa/nex_oa/token_validation_service.py \
  --coverage-target scripts/smoke/run_oa_token_validation.py \
  --smoke scripts/smoke/run_oa_token_validation.py
```
