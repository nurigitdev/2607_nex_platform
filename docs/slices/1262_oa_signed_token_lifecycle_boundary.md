# Slice 1262: OA signed-token lifecycle boundary audit

## Goal

Freeze the S127 ownership and privacy boundary before adding signing-key,
revocation, token-exchange, JWKS, or introspection persistence.

## Decision

- NeX-OA owns `oa_signing_keys` and `oa_token_revocations`; both table names
  remain under 30 characters.
- S127 initially issues the `service_access` profile through the
  `client_credentials` grant using S126 service credentials.
- Tokens use RS256 with RSA keys of at least 3072 bits and a maximum lifetime
  of 300 seconds.
- PostgreSQL may store public JWK metadata and an external private-key custody
  reference. It may never store private key material or raw access tokens.
- Revocation persistence uses a SHA-256 digest of `jti`; raw token logging and
  cross-service database reads remain forbidden.
- JWKS and introspection are OA APIs. Consumers validate through those APIs or
  locally cached JWKS, never through the OA database.
- Actual `nex_oa_test` evidence is required at Slice 1270. Remote model
  providers are outside S127.

## Slice Order

1. 1262 boundary audit and refactoring checkpoint
2. 1263 signing-key and revocation domain contracts
3. 1264 persistence migration
4. 1265 durable repository
5. 1266 key lifecycle and JWKS service plus Checkpoint Gate
6. 1267 client-credential token exchange and RS256 issuance
7. 1268 signed-token validation and introspection runtime
8. 1269 protected API, OpenAPI, JSON Schema, and privacy hardening
9. 1270 actual PostgreSQL smoke
10. 1271 closure and Full Gate

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_signed_token_lifecycle_boundary.py \
  --coverage-target services/nex-oa/nex_oa/signed_token_lifecycle_boundary.py \
  --coverage-target scripts/smoke/run_oa_signed_token_lifecycle_boundary.py \
  --smoke scripts/smoke/run_oa_signed_token_lifecycle_boundary.py
```
