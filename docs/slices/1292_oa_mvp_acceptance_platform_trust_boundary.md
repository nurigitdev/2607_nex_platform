# Slice 1292: OA MVP acceptance and platform trust boundary audit

## Goal

Freeze S130 acceptance before adding evidence. The scope is OA-FR-001 through
OA-FR-005 and the trust path consumed by AE, CX, MO, and AG.

## Decision

- `nex-oa` remains the only identity, credential, session, membership,
  service-principal, signing-key metadata, and revocation authority.
- Final evidence must use `nex_oa_user@nex_oa_test`, apply all OA migrations,
  reconstruct runtime adapters, and leave zero smoke-owned rows.
- Key rotation must prove old/new JWKS overlap, one active signing key, and
  verification after OA adapter reconstruction.
- Revocation must remain effective after repository and validation-service
  reconstruction.
- AE, CX, MO, and AG must accept scoped RS256 service tokens in `SIGNED_ONLY`
  mode, reject mock tokens, and require introspection for sensitive routes.
- Private signing keys remain outside PostgreSQL. The protected test uses an
  in-memory external-custody adapter and stores only custody references.
- OA-FR-005 requires durable, privacy-safe login, token-validation, and
  service-auth failure evidence. Signed-token failures are hardened in Slice
  1293 before acceptance proceeds.
- S130 creates no new table. DGX and model providers are outside this scope.
- External IdP registration, browser PKCE product integration, production
  KMS/HSM activation, delegated-user access tokens, and SAML remain deployment
  or post-MVP work; they do not weaken the accepted local credential and
  service-trust boundary.

## Quality cadence

- Slice Gate: Slices 1292-1300
- Checkpoint Gate: Slice 1296
- Full Gate: Slice 1301

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_mvp_acceptance_platform_trust_boundary.py \
  --coverage-target scripts/smoke/run_oa_mvp_acceptance_platform_trust_boundary.py \
  --smoke scripts/smoke/run_oa_mvp_acceptance_platform_trust_boundary.py
```
