# Slice 1264: OA signed-token persistence migration

## Outcome

- Added `oa_signing_keys` for public JWK metadata, external custody references,
  forward-only key state, activation/signing/verification windows, and revision.
- Added `oa_token_revocations` for SHA-256 `jti` digests, bounded reason codes,
  and automatic relevance expiry with the original token.
- Enforced one ACTIVE key per issuer through a partial unique index.
- Added expiry, state, and subject lookup indexes without exceeding PostgreSQL's
  identifier limit; both table names remain under 30 characters.
- DDL explicitly rejects private JWK members and contains no private-key,
  client-secret, raw-token, or access-token column.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_signed_token_migration.py \
  --coverage-target scripts/smoke/run_oa_signed_token_migration.py \
  --smoke scripts/smoke/run_oa_signed_token_migration.py
```
