# Slice 1247: OA service-principal credential boundary and S126 handoff

## Goal

Turn the S125 trust decisions into an implementation-ready S126 handoff
without prematurely adding credentials, keys, revocations, or tables.

## Decision

- OA owns service principals, client credentials, signing keys, revocations,
  token exchange, JWKS, and introspection. Other services use OA APIs and
  never read the OA database directly.
- A service principal has an explicit service ID, status, audience allowlist,
  scope allowlist, and optimistic revision. No audience or scope defaults are
  granted silently.
- A credential secret is displayed once at creation or rotation and only an
  Argon2id hash plus a short non-secret hint is persisted. Raw credentials and
  access tokens are forbidden in records and logs.
- Credential lifetime is at most 90 days. Rotation overlap is at most 24
  hours, with no more than two simultaneously active credentials per
  principal. Signed access tokens remain limited to five minutes.
- Proposed S126 tables are `oa_service_principals`, `oa_service_creds`,
  `oa_signing_keys`, and `oa_token_revocations`; all names are under 30
  characters. S125 creates none of them.
- S126 implementation order is migration/repository, one-time credential
  lifecycle, signed token exchange, JWKS/introspection, then signed-only
  cross-service rollout.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_service_principal_boundary.py \
  --test tests/test_oa_service_principal_handoff.py \
  --coverage-target services/nex-oa/nex_oa/service_principal_boundary.py \
  --coverage-target scripts/smoke/run_oa_service_principal_handoff.py \
  --smoke scripts/smoke/run_oa_service_principal_handoff.py
```
