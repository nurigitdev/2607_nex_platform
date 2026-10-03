# Slice 1271: S127 OA signed-token lifecycle closure

## Closure

S127 closes the OA-owned `service_access` signed-token runtime:

- `oa_signing_keys` persists public JWK metadata and an external private-key
  reference; `oa_token_revocations` persists only SHA-256 JTI digests.
- RS256 issuance uses RSA keys of at least 3072 bits and fixes service-token
  lifetime at five minutes.
- Client credentials are authenticated against S126 state before audience and
  scope allowlists are applied.
- Local validation checks signature, issuer, audience, scope, time, key state,
  credential revision, principal state, and revocation. Introspection exposes
  only bounded metadata.
- Four signed-token operations and four canonical response contracts reject
  private key material, client secrets, raw tokens, and raw JTI values.
- Actual `nex_oa_test` evidence covers all 16 migrations, restart-safe key and
  revocation reads, digest-only persistence, and zero cleanup residue.

## Deployment boundary

The implementation is ready, but the default OA composition root deliberately
uses `UnavailableOaRsaSigningProvider`. Production issuance remains fail-closed
until a KMS, Vault, PKCS#11, or equivalent external-custody adapter is injected.
The in-memory RSA provider is limited to deterministic test and smoke evidence.

S127 does not claim that every consumer service has moved to signed-only
admission. External signing custody integration and ordered cross-service
rollout remain the S128 handoff. Remote model providers are unrelated.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_s127_oa_signed_token_lifecycle_closure.py --summary

NEX_OA_SIGNED_TOKEN_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='<OA test database URL>' \
./scripts/quality/run_quality_gate.sh
```

The Full Gate is the authoritative regression, statement/branch coverage,
contract, closure, and protected PostgreSQL acceptance result for S127.

## Observed Full Gate

- Regression: `10,492 passed, 16 skipped`
- Statement coverage: `98.46%`
- Branch coverage: `97.09%`
- Contracts: `151` schemas, `209` positive examples, `179` negative
  examples, and `7` OpenAPI documents
- S127 PostgreSQL smoke: `PASS` against `nex_oa_test` as `nex_oa_user`,
  with all `16` migrations current, `1` signing key and `1` revocation
  persisted, restart validation confirmed, and no cleanup residue
- S127 closure: `PASS`, with `9/9` evidence items, `5/5` components, and
  `4` signed-token operations; production custody remains explicitly bound to
  an external adapter
