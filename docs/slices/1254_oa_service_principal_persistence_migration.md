# Slice 1254: OA service-principal persistence migration

## Goal

Add the S126 durable schema without pulling S127 signing or token-revocation
storage into this requirement.

## Implementation

- Added `oa_service_principals` for service identity, explicit audience/scope
  allowlists, status, and optimistic revision.
- Added `oa_service_creds` for Argon2id hashes, non-secret hints, lifecycle
  status, expiry, rotation grace, last-use metadata, and optimistic revision.
- Added service/status, principal/status/expiry, and expiry cleanup indexes.
- Kept all table names under 30 characters and all PostgreSQL identifiers
  within the 63-character limit.
- Deferred `oa_signing_keys` and `oa_token_revocations` to S127.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_service_principal_migration.py \
  --coverage-target scripts/smoke/run_oa_service_principal_migration.py \
  --smoke scripts/smoke/run_oa_service_principal_migration.py
```

Actual PostgreSQL migration evidence remains scheduled for Slice 1260.
