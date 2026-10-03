# Slice 1245: OA signing algorithm and key custody policy

## Goal

Freeze the production signing algorithm, external private-key custody,
rotation lifecycle, and database storage boundary before implementation.

## Decision

- Production allows only `RS256` with an RSA modulus of at least 3072 bits.
  `alg=none`, symmetric signing, and algorithm selection from token input are
  forbidden.
- Production private keys must be resolved through `kms://`, `vault://`, or
  `pkcs11://` custody adapters. `file://` is allowed only in explicit test or
  development profiles. Inline, environment, URL credential, query, and
  fragment key material are forbidden.
- PostgreSQL may hold only public JWK, key state, activation/retirement times,
  revision, and an external private-key locator. Private RSA JWK members are
  rejected, and plaintext private keys are never stored in the database.
- Normal lifecycle is `PREPUBLISHED -> ACTIVE -> VERIFY_ONLY -> RETIRED`.
  `PREPUBLISHED`, `ACTIVE`, and `VERIFY_ONLY` may transition immediately to
  terminal `REVOKED`; rollback to a signing state is forbidden.
- A new key must be published at least 330 seconds before activation. An old
  key remains verifiable at least 330 seconds after signing stops, covering
  the 300-second token TTL plus 30-second skew.
- Exactly one active signing key per issuer is required. S125 defines this
  invariant but adds no key table or private-key adapter; those belong to S126.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_signing_key_policy.py \
  --test tests/test_oa_signing_key_policy_smoke.py \
  --coverage-target services/nex-oa/nex_oa/signing_key_policy.py \
  --coverage-target scripts/smoke/run_oa_signing_key_policy.py \
  --smoke scripts/smoke/run_oa_signing_key_policy.py
```
