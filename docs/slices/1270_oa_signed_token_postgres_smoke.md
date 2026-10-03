# Slice 1270: OA signed-token actual PostgreSQL smoke evidence

## Outcome

- Added a protected smoke runner that requires the exact `nex_oa_user` and
  `nex_oa_test` target and applies all 16 OA migrations before execution.
- The workflow persists a service principal, credential, public signing-key
  metadata, and a SHA-256 JTI revocation digest through SQLAlchemy repositories.
- It issues and verifies an RS256 token, reconstructs repositories to simulate
  restart, verifies active introspection, persists revocation, and verifies the
  restarted validator returns inactive.
- SQL observations prove that public JWK rows contain no private JWK members,
  the compact token is absent, and the revocation row contains the digest rather
  than raw JTI. All smoke-owned rows are deleted and residue is asserted zero.
- The 3072-bit RSA private key exists only in the smoke process's in-memory
  custody and is never serialized.

## Protected Verification

```bash
NEX_OA_SIGNED_TOKEN_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://.../nex_oa_test' \
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_signed_token_postgres_smoke.py \
  --coverage-target services/nex-oa/nex_oa/signed_token_postgres_smoke.py \
  --coverage-target scripts/smoke/run_oa_signed_token_postgres_smoke.py \
  --smoke scripts/smoke/run_oa_signed_token_postgres_smoke.py
```

## Observed Evidence

- Actual database and role: `nex_oa_test` / `nex_oa_user`
- Migration ledger: `16/16`
- Protected test: `1 passed`
- Slice Gate: `790 passed, 5 skipped`
- Persisted signing keys and revocations: `1` / `1`
- Private JWK members and raw-token matches: `0` / `0`
- Cleanup residue: `0`
