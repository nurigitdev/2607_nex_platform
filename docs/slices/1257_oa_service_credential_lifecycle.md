# Slice 1257: OA one-time client-credential lifecycle

## Goal

Implement secure client-credential issue, rotation, verification, revocation,
and expiry behavior without adding signed access-token issuance.

## Implementation

- Generates high-entropy client secrets and stores only Argon2id hashes plus a
  six-character non-secret hint.
- Returns the raw client secret only from issue and rotation responses.
- Enforces a maximum 90-day lifetime, two active credentials, disabled
  principal rejection, expiry, revision checks, and a maximum 24-hour grace.
- Performs old-credential rotation and new-credential insertion atomically in
  memory and SQLAlchemy repositories.
- Added internal credential verification for the future S127 token exchange;
  no access token, signing key, JWKS, or introspection endpoint is introduced.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_service_credential_service.py \
  --coverage-target services/nex-oa/nex_oa/service_principal_service.py \
  --coverage-target services/nex-oa/nex_oa/service_principal_repository.py
```
