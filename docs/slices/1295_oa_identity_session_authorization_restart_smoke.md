# Slice 1295: OA identity, session, and authorization restart smoke

## Outcome

- Added a protected smoke locked to `nex_oa_user@nex_oa_test`.
- Applies the full OA migration inventory before writing smoke-owned data.
- Persists one tenant, subject, membership, Argon2id credential, browser
  session, role, group, group membership, group-role assignment, and four
  authorization events.
- Disposes the initial PostgreSQL engine and reconstructs the OA subject,
  membership, credential, session, authorization repository, and resolver
  stack.
- Proves credential verification, membership readback, active session
  introspection, and effective role/group/scope resolution after restart.
- Verifies the raw password is absent from PostgreSQL and removes all
  smoke-owned rows with zero residue.

## Protected execution

```bash
NEX_OA_IDENTITY_RESTART_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_identity_session_authorization_restart_smoke.py \
  --coverage-target scripts/smoke/run_oa_identity_session_authorization_restart_smoke.py \
  --smoke scripts/smoke/run_oa_identity_session_authorization_restart_smoke.py
```

The database URL is supplied only through the local environment.

## Verified evidence

- Actual PostgreSQL target: `nex_oa_user@nex_oa_test`
- Migration inventory: `17`
- Restart read paths: `4`
- Persisted row classes: `10`
- Cleanup residue: `0`
- Slice Gate: `906 passed`, `7 skipped`
- Coverage: statement `98.49%`, branch `97.97%`
- Smoke runner coverage: statement `99.32%`, branch `95.45%`
