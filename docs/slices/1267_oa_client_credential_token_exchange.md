# Slice 1267: OA client-credential token exchange and RS256 issuance

## Outcome

- Added a client-credential exchange service that authenticates S126 service
  credentials, enforces the principal audience/scope allowlists, and emits a
  fixed five-minute `service_access` token.
- Added an RS256 signing-provider boundary backed by `cryptography`. The
  in-memory implementation is limited to test/development custody and never
  serializes a private key.
- Added `credential_id` to the canonical service-token claims. Together with
  `credential_revision`, this provides unambiguous credential revocation and
  rotation lineage for Slice 1268 introspection.
- The compact access token is returned once. It is not persisted or logged;
  database records continue to contain only external private-key references
  and public JWK metadata.
- Added signature verification and fail-closed coverage for invalid grants,
  secrets, clocks, audiences, scopes, signing windows, and unavailable custody.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_token_signing.py \
  --test tests/test_nex_oa_token_exchange_service.py \
  --test tests/test_nex_oa_service_principal_service.py \
  --test tests/test_oa_production_token_profiles.py \
  --test tests/test_oa_token_exchange_smoke.py \
  --coverage-target services/nex-oa/nex_oa/token_signing.py \
  --coverage-target services/nex-oa/nex_oa/token_exchange_service.py \
  --coverage-target scripts/smoke/run_oa_token_exchange.py \
  --smoke scripts/smoke/run_oa_token_exchange.py
```
