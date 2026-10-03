# Slice 1251: S125 OA production-trust closure

## Goal

Close S125 by binding the production trust decisions, privacy contracts, and
actual PostgreSQL baseline into an implementation-ready S126 handoff.

## Closure

- NeX-OA owns production token trust while browser sessions remain opaque and
  OA-backed.
- The two signed access-token profiles are `service_access` and
  `delegated_user_access`, issued by `urn:nex-platform:oa` with a five-minute
  maximum lifetime.
- Signing is restricted to RS256 with RSA keys of at least 3072 bits. Private
  key material remains outside PostgreSQL under an external custody locator.
- Local validation is fail closed. JWKS cache TTL is 300 seconds, an unknown
  key gets one bounded refresh, and revocation-sensitive operations require
  introspection with a three-second timeout.
- `TEST_MOCK -> DUAL_READ -> SIGNED_ONLY` is forward only. Production silent
  mock fallback is forbidden.
- S125 policy readiness is complete, but signed-token runtime readiness is
  deliberately `IMPLEMENTATION_PENDING`. S126 owns durable service principal,
  credential, signing-key and revocation storage; token exchange; JWKS;
  introspection; and ordered cross-service rollout.
- S125 creates no new database table. The four short proposed S126 table names
  remain `oa_service_principals`, `oa_service_creds`, `oa_signing_keys`, and
  `oa_token_revocations`.
- The actual PostgreSQL baseline and privacy evidence are closed. DGX and
  remote model providers are outside this requirement.

## Quality Cadence

- Slice Gate: Slices 1242-1250
- Checkpoint Gate: Slice 1246
- Full Gate: Slice 1251

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_s125_oa_production_trust_closure.py \
  --summary

NEX_OA_TRUST_BASELINE_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./scripts/quality/run_quality_gate.sh
```

The protected database URL is supplied only through the local environment.

## Observed Evidence

- S125 closure: `PASS`, evidence `9/9`, components `5/5`, signed profiles
  `2`, signed runtime `IMPLEMENTATION_PENDING`, next requirement `S126`
- Actual PostgreSQL baseline: `PASS` on `nex_oa_test` as `nex_oa_user`,
  migration ledger `14/14`, cleanup residue `0`
- Python regression: `10,236 passed`, `14 skipped`, `123 warnings`
- Statement coverage: `98.47%`
- Branch coverage: `97.07%` with the enforced `94%` minimum
- AE Web regression: `293 passed`, `0 failed`
- Contract validation: `141` schemas, `199` positive examples, `169`
  negative examples, and `7` OpenAPI documents
- Full Gate exit status: `0`
