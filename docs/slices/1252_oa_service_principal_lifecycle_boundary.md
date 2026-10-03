# Slice 1252: OA service-principal lifecycle boundary audit

## Goal

Freeze the S126 ownership boundary before adding durable service-principal or
client-credential runtime behavior.

## Decision

- S126 owns service-principal registration, status, audience/scope allowlists,
  optimistic revision, and client-credential issue, rotation, expiry, and
  revocation.
- S126 creates only `oa_service_principals` and `oa_service_creds`. Both names
  are under 30 characters.
- Credential secrets are displayed once at creation or rotation. PostgreSQL
  stores only an Argon2id hash and a short non-secret hint.
- Cross-service database reads and implicit audience or scope grants remain
  forbidden.
- Signing-key custody, signed token exchange, JWKS, introspection, token
  revocation storage, and signed-only rollout move to S127. Their reserved
  tables are `oa_signing_keys` and `oa_token_revocations`.
- Actual `nex_oa_test` PostgreSQL evidence is required at Slice 1260. DGX and
  remote model providers are outside S126.

## Slice Order

1. 1252 boundary audit and S126/S127 split
2. 1253 domain contracts
3. 1254 persistence migration
4. 1255 durable repository
5. 1256 principal lifecycle service and Checkpoint Gate
6. 1257 one-time credential issue, rotation, expiry, and revocation
7. 1258 protected API, scope, and audit wiring
8. 1259 OpenAPI, JSON Schema, and privacy hardening
9. 1260 actual PostgreSQL smoke
10. 1261 closure and Full Gate

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_service_principal_lifecycle_boundary.py \
  --coverage-target services/nex-oa/nex_oa/service_principal_lifecycle_boundary.py \
  --coverage-target scripts/smoke/run_oa_service_principal_lifecycle_boundary.py \
  --smoke scripts/smoke/run_oa_service_principal_lifecycle_boundary.py
```
