# Slice 1298: OA cross-service SIGNED_ONLY trust smoke

## Outcome

- Updated the older S128 platform-token smoke from migration inventory `16`
  to the current OA inventory `17`.
- Added a protected PostgreSQL smoke locked to
  `nex_oa_user@nex_oa_test`.
- Issues separate RS256 service tokens for AE API, CX, MO, and AG, disposes the
  issuing OA runtime, and reconstructs OA validation from persisted state.
- Runs every consumer in `SIGNED_ONLY` and exercises an HTTP `ADMIN` route that
  requires local signature validation plus OA introspection.
- Proves mock tokens are denied, active signed tokens are admitted, and each
  signed token is denied after its durable OA revocation.
- Verifies four digest-only revocations, no raw secret/token or private JWK
  persistence, and zero cleanup residue.

The four consumers use in-process FastAPI HTTP clients while OA trust state is
read from actual PostgreSQL. This isolates the trust protocol from deployment
network variability without replacing database persistence with mocks.

## Protected execution

```bash
NEX_OA_CROSS_SERVICE_TRUST_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_cross_service_trust_smoke.py \
  --coverage-target scripts/smoke/run_oa_cross_service_trust_smoke.py \
  --smoke scripts/smoke/run_oa_cross_service_trust_smoke.py
```

The database URL is supplied only through the local environment.

## Verified evidence

- Actual PostgreSQL target: `nex_oa_user@nex_oa_test`
- Current migration inventory: `17`
- SIGNED_ONLY consumers passed: `4/4`
- Issued service tokens: `4`
- Post-revocation sensitive-route denials: `4/4`
- Cleanup residue: `0`
- Slice Gate: `953 passed`, `10 skipped`
- Coverage: statement `99.07%`, branch `98.09%`
- Smoke runner coverage: statement `100.00%`, branch `100.00%`
- Revalidated S128 platform smoke: `4/4` consumers, `4` tokens, residue `0`
