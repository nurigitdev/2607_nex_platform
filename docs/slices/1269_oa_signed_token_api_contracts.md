# Slice 1269: OA signed-token API, contracts, and privacy hardening

## Outcome

- Replaced the OA composition root's mock token routes with RS256-backed
  service-token exchange, signed introspection, revocation, and public JWKS
  routes. The shared app factory retains an explicit compatibility switch so
  historical mock-runtime tests remain reversible.
- Introspection and revocation require a valid signed bearer for `nex-oa` plus
  `token:introspect` or `token:revoke`; token exchange authenticates the S126
  client credential directly.
- The default OA runtime uses a fail-closed external-custody placeholder. A
  concrete KMS/Vault/PKCS#11 signer must be injected for production issuance;
  private key files are never loaded by the service composition root.
- Added canonical JSON Schemas, positive and privacy-negative examples, and
  OpenAPI 3.1 definitions for all four surfaces. Public schemas reject private
  key references, client secrets, raw introspected tokens, and JTI leakage.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_signed_token_api.py \
  --test tests/test_nex_oa_token_signing.py \
  --test tests/test_oa_signed_token_api_smoke.py \
  --coverage-target services/nex-oa/nex_oa/signed_token_api.py \
  --coverage-target scripts/smoke/run_oa_signed_token_api.py \
  --smoke scripts/smoke/run_oa_signed_token_api.py
```
