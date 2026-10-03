# Slice 1263: OA signing-key and revocation domain contracts

## Outcome

- Added revisioned signing-key registration and forward-only state transitions:
  `PREPUBLISHED -> ACTIVE -> VERIFY_ONLY -> RETIRED`, with emergency revocation.
- Enforced canonical OA issuer, RS256 metadata, minimum publication lead,
  signing windows, verification overlap, and custody-reference policy.
- Added deterministic JWKS projection that includes only publishable,
  unexpired public keys and rejects private JWK members or duplicate `kid`.
- Added token-revocation records that persist only SHA-256 `jti` digests and
  expire with the original access token.
- Kept the domain independent of PostgreSQL, HTTP, and private-key loading.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_signed_tokens.py \
  --coverage-target services/nex-oa/nex_oa/signed_tokens.py \
  --coverage-target scripts/smoke/run_oa_signed_token_domain.py \
  --smoke scripts/smoke/run_oa_signed_token_domain.py
```
