# Slice 1227: OA password rotation and session revocation

## Result

- Added a dedicated `credential:security:write` boundary for password change
  and operator reset requests.
- Password change verifies the current secret, rejects immediate reuse, clears
  lockout state, and returns the credential to `ACTIVE`.
- Operator reset issues a temporary Argon2id secret and moves the credential
  to `PASSWORD_RESET_REQUIRED` without reactivating disabled identities.
- PostgreSQL rotates the credential and revokes all matching active sessions
  in one transaction. A session-store failure rolls the credential update back.
- Responses contain neither password/hash material nor revoked session IDs.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_credential_security.py \
  --test tests/test_oa_credential_rotation_runner.py \
  --coverage-target services/nex-oa/nex_oa/credential_security.py \
  --coverage-target scripts/smoke/run_oa_credential_rotation.py \
  --smoke scripts/smoke/run_oa_credential_rotation.py
```

Observed result: `278 passed, 1 skipped`; overall statement `98.03%`, overall
branch `95.79%`, credential-security branch `98.15%`, and smoke checks `7/7`.
