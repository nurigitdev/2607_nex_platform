# Slice 1283: OA OIDC provider and external-identity domain

## Outcome

- Added strict OIDC provider records with exact issuer, client audience,
  discovery URL, RS256-only ID-token policy, status, and revision.
- Added pre-provisioned external identity links from an opaque subject digest
  to the canonical OA tenant and subject.
- External subject values are combined with the issuer and SHA-256 hashed;
  raw subjects are neither persisted nor returned.
- Provider secret, token, email, employee-id, phone, and raw profile fields are
  rejected rather than silently retained.
- Production provider URLs require HTTPS. Plain HTTP is accepted only for an
  explicitly enabled localhost loopback used by protected smoke tests.
- Resolution fails closed for issuer, audience, provider status, link status,
  or exact subject-digest mismatch.

No database table or external provider call is introduced in this Slice.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_federated_identities.py \
  --coverage-target services/nex-oa/nex_oa/federated_identities.py \
  --coverage-target scripts/smoke/run_oa_federated_identity_domain.py \
  --smoke scripts/smoke/run_oa_federated_identity_domain.py
```
