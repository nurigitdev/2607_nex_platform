# Slice 1242: OA production trust boundary audit

## Goal

Start S125 by freezing the production token trust boundary before adding
service principals, signing keys, JWKS, or signed token issuance.

## Decision

- NeX-OA owns service and delegated-user token issuance, introspection,
  revocation semantics, signing metadata, and privacy-safe auth events.
- Browser login remains an opaque OA-backed session. A signed token is not
  stored directly in a browser-readable location.
- Production targets short-lived signed `service_access` and
  `delegated_user_access` profiles. Mock-token fallback is forbidden in the
  production profile and remains available only to explicit test profiles.
- Services must validate signature, issuer, audience, time bounds, and scopes
  locally. Revocation-sensitive operations additionally require live
  introspection according to the policy frozen later in S125.
- Plaintext private signing keys are forbidden in PostgreSQL. Key custody is
  finalized before implementation in Slice 1245.
- S125 is an audit and decision requirement: it adds no database table and
  mutates no existing OA record. Actual `nex_oa_test` baseline evidence is
  still mandatory at Slice 1250.
- DGX and model providers are outside this requirement.
- OIDC/SAML, MFA, recovery delivery, HSM integration, explicit deny, and nested
  groups remain deferred.

## Cadence

Slices 1242 through 1251 cover boundary, inventory, token profiles, signing
and custody, validation and revocation, service-principal handoff,
cross-service rollout, privacy/contracts, PostgreSQL baseline evidence, and
closure. Slice Gate runs through 1250, Checkpoint Gate at 1246, and Full Gate
at 1251.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_production_trust_boundary.py \
  --coverage-target scripts/smoke/run_oa_production_trust_boundary.py \
  --smoke scripts/smoke/run_oa_production_trust_boundary.py
```
