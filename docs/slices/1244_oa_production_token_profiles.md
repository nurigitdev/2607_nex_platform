# Slice 1244: OA canonical production token profiles

## Goal

Freeze interoperable signed-token shapes before selecting the signing
algorithm, key custody, or runtime validation implementation.

## Decision

- Production issuer is the deployment-independent identifier
  `urn:nex-platform:oa`; each access token has one NeX service audience.
- Signed profiles are `service_access` and `delegated_user_access`. Browser
  login remains an opaque OA-backed session and is not a signed profile.
- JOSE headers require `alg`, `kid`, and `typ=at+jwt`. Algorithm allowlisting
  is finalized in Slice 1245; unsigned `alg=none` is already forbidden.
- Both profiles use a 300-second maximum TTL and 30-second clock-skew bound.
  `iat`, `nbf`, and `exp` use integer NumericDate values.
- OAuth-style `scope` is a normalized, space-delimited string. A service token
  includes `service_id` and `credential_revision`.
- A delegated token includes tenant/user identity, a non-secret `session_ref`,
  `authorization_revision`, and authorized party `azp`. Raw session handles,
  credentials, secrets, roles, and groups are forbidden. This limits leakage
  and stale authorization while retaining scope snapshot traceability.
- S125 defines and tests the profile but does not sign or accept it in the
  current runtime. Implementation remains the S126 handoff.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_production_token_profiles.py \
  --test tests/test_oa_production_token_profiles_smoke.py \
  --coverage-target services/nex-oa/nex_oa/production_token_profiles.py \
  --coverage-target scripts/smoke/run_oa_production_token_profiles.py \
  --smoke scripts/smoke/run_oa_production_token_profiles.py
```
