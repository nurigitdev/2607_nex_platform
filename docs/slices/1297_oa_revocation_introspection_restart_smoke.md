# Slice 1297: OA revocation and introspection restart smoke

## Outcome

- Added a protected PostgreSQL smoke locked to
  `nex_oa_user@nex_oa_test`.
- Issues and introspects an active RS256 service token, disposes the OA runtime,
  and proves it remains active from reconstructed repositories.
- Persists an operator revocation, disposes the second runtime, and proves the
  token becomes inactive with `oa.token_revoked` after another restart.
- Verifies revocation lookup is restart-safe while PostgreSQL stores only the
  SHA-256 token-id digest, never the raw `jti` or access token.
- Removes all principal, credential, signing-key, and revocation rows created
  by the smoke and requires zero residue.

## Protected execution

```bash
NEX_OA_REVOCATION_RESTART_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_revocation_introspection_restart_smoke.py \
  --coverage-target scripts/smoke/run_oa_revocation_introspection_restart_smoke.py \
  --smoke scripts/smoke/run_oa_revocation_introspection_restart_smoke.py
```

The database URL is supplied only through the local environment.

## Verified evidence

- Actual PostgreSQL target: `nex_oa_user@nex_oa_test`
- Migration inventory: `17`
- Revocation workflow checks: `5`
- OA runtime restarts: `2`
- Cleanup residue: `0`
- Slice Gate: `922 passed`, `9 skipped`
- Coverage: statement `98.44%`, branch `97.74%`
- Smoke runner coverage: statement `100.00%`, branch `100.00%`
