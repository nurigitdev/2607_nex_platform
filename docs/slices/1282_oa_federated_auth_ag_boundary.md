# Slice 1282: OA federated authentication and AG integration boundary

## Goal

Freeze the S129 trust, identity-linking, session, and AG-consumer boundaries
before adding federated authentication runtime behavior.

## Decision

- OA owns external identity-provider trust, exact external-subject mapping, and
  issuance of the existing opaque OA user session.
- S129 implements OIDC Authorization Code with PKCE and RS256 ID-token
  verification. SAML 2.0 remains deferred.
- External identities must be pre-provisioned and matched by exact provider,
  issuer, and subject. Automatic email or employee-id account linking is
  forbidden.
- Provider secrets and raw external tokens are not persisted. External tokens
  are never forwarded to AG.
- AG does not validate IdP tokens or read the OA database. It consumes only an
  OA-normalized operator context and continues to require an effective admin
  role for protected operator surfaces.
- Two short OA-owned tables are planned: `oa_fed_providers` and
  `oa_fed_identities`. Slice 1290 must prove them against actual `nex_oa_test`.
- A real enterprise IdP is not required to close S129. A protected local OIDC
  loopback proves discovery, JWKS, signature, nonce, mapping, OA session, and AG
  authorization behavior without weakening the production boundary.

## Slice Order

1. 1282 boundary audit and refactoring checkpoint
2. 1283 OIDC provider and external-identity domain
3. 1284 persistence migration and repository
4. 1285 OIDC discovery, JWKS, and ID-token verifier
5. 1286 federated login/session orchestration and Checkpoint Gate
6. 1287 AG federated operator-context adoption
7. 1288 AG authorization and audit hardening
8. 1289 contracts, observability, and privacy hardening
9. 1290 actual PostgreSQL and protected loopback OIDC smoke
10. 1291 S129 closure and Full Gate

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --test tests/test_oa_federated_auth_ag_boundary.py \
  --coverage-target services/nex-oa/nex_oa/federated_auth_boundary.py \
  --coverage-target scripts/smoke/run_oa_federated_auth_ag_boundary.py \
  --smoke scripts/smoke/run_oa_federated_auth_ag_boundary.py
```
