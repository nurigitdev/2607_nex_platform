# Slice 1240: OA authorization PostgreSQL smoke evidence

## Result

- Added a protected smoke runner that only accepts
  `nex_oa_user@.../nex_oa_test` and fails closed for missing or wrong targets.
- Applied the pending `1234_oa_group_role_authorization` migration to the
  actual test database; all 14 OA migrations are now current.
- Exercised protected membership bootstrap, role/group/member/assignment
  mutations, effective authorization reads, and event reads through FastAPI.
- Proved two active sessions were revoked after assignment and role changes,
  while stale revision and missing-admin-scope requests were rejected.
- Rebuilt the authorization repository and verified role/group/assignment
  readback from PostgreSQL.
- Queried database/role, row revisions, five event records, actor/request/trace
  lineage, and two revocation events directly from PostgreSQL.
- Deleted smoke data from nine related tables and verified zero residue.
- DGX and remote model providers were not required.

## Verification

```bash
NEX_OA_AUTHORIZATION_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_authorization_postgres_smoke.py \
  --coverage-target services/nex-oa/nex_oa/authorization_postgres_smoke.py \
  --coverage-target scripts/smoke/run_oa_authorization_postgres_smoke.py \
  --smoke scripts/smoke/run_oa_authorization_postgres_smoke.py
```

Initial protected evidence:

- Database/role: `nex_oa_test` / `nex_oa_user`
- Migration: `1234_oa_group_role_authorization` applied (`14` planned,
  `13` previously current)
- Workflow checks: `10/10`
- Authorization events: `5`
- Revoked sessions: `2`; active smoke sessions: `0`
- Restart readback: role/group/group-role each `1`
- Cleanup: `9` table categories, residue `0`
- Protected pytest: `20 passed`, no skip

Observed Slice Gate:

- Tests: `410 passed`, `2 skipped`
- Statement coverage: `98.75%`
- Branch coverage: `97.38%`
- Smoke evaluator coverage: `100.00%` statement / `100.00%` branch
- Smoke runner coverage: `100.00%` statement / `100.00%` branch
- Contract validation: `140` schemas, `198` positive examples,
  `168` negative examples, `7` OpenAPI documents
- PostgreSQL smoke: `PASS`; events `5`, revoked sessions `2`, residue `0`
