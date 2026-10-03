# Slice 1285: OA OIDC discovery, JWKS, and ID-token verifier

## Outcome

- Added exact-issuer OIDC discovery validation and bounded JWKS loading with a
  five-minute cache, at most 16 keys, and unknown-key refresh.
- Restricted ID-token verification to RS256 and rejected remote key headers,
  embedded certificates, private JWK material, malformed RSA parameters, and
  oversized tokens.
- Enforced issuer, audience, authorized party, nonce, issued-at, not-before,
  expiration, one-hour maximum lifetime, and bounded clock skew.
- Public verification and cache projections expose only digests for external
  subject, nonce, and key id. Raw ID tokens and external identifiers remain
  private to the in-process verification step.
- Added deterministic static-document evidence. No network call or live IdP is
  required in this Slice.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_oidc_verifier.py \
  --coverage-target services/nex-oa/nex_oa/oidc_verifier.py \
  --coverage-target scripts/smoke/run_oa_oidc_verifier.py \
  --smoke scripts/smoke/run_oa_oidc_verifier.py
```
