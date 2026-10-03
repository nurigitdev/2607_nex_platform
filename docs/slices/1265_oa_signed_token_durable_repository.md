# Slice 1265: OA signed-token durable repository

## Outcome

- Added a shared repository protocol with memory and SQLAlchemy adapters.
- Signing-key writes enforce optimistic revision and one ACTIVE key per issuer.
- Public JWK and lifecycle windows survive SQLAlchemy restart reads while the
  repository never accepts or returns private key material.
- Revocations are uniquely addressed by SHA-256 `jti` digest and can be purged
  once the original token expires.
- SQLite regression covers SQL shape and restart behavior; actual PostgreSQL
  execution remains protected until Slice 1270.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_signed_token_repository.py \
  --test tests/test_oa_signed_token_repository_smoke.py \
  --coverage-target services/nex-oa/nex_oa/signed_token_repository.py \
  --coverage-target scripts/smoke/run_oa_signed_token_repository.py \
  --smoke scripts/smoke/run_oa_signed_token_repository.py
```
