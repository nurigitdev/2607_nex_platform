# Slice 0254: OA User Login PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for the OA employee id/password login
path introduced in Slice 0253.

## Implemented

- Added `scripts/smoke/run_oa_user_login_postgres_smoke.py`.
- Added the runner to the quality gate as a default-skipped protected smoke.
- The runner requires `NEX_OA_USER_LOGIN_POSTGRES_SMOKE=1` and permits write
  execution only with the `test` profile.
- The smoke applies `nex-oa` migrations, then exercises:
  - local credential seed
  - tenant membership ensure
  - OA user login
  - session readback
  - session introspection
  - session revocation
  - revoked-session introspection
  - PostgreSQL DB observations
  - smoke-row cleanup

## Security Boundary

- The runner never prints raw passwords, password hashes, access tokens, cookie
  values, service credentials, or the unredacted database URL.
- DB observations include only counts, statuses, subject ids, scopes/roles, and
  the hash algorithm id.
- Cleanup deletes smoke sessions, credentials, memberships, subjects, and
  tenants by the generated smoke ids.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_oa_user_login_postgres_smoke.py tests/test_nex_oa_user_login.py -q`
  - Result: `15 passed, 1 warning`
- Smoke runner module coverage:
  `./.venv/bin/pytest tests/test_oa_user_login_postgres_smoke.py --cov=run_oa_user_login_postgres_smoke --cov-branch --cov-report=term-missing -q`
  - Result: `7 passed, 1 warning`; `run_oa_user_login_postgres_smoke` at 100% statement and branch coverage.
- Live PostgreSQL smoke against `nex_oa_test`:
  `NEX_OA_USER_LOGIN_POSTGRES_SMOKE=1 NEX_OA_TEST_DATABASE_URL=... ./.venv/bin/python scripts/smoke/run_oa_user_login_postgres_smoke.py`
  - Result: `PASS`
  - Migration: `planned_count=11`, `applied=["0252_oa_local_credential_foundation"]`, `skipped_count=10`
  - DB observations: `credential_count=1`, `membership_count=1`, `session_count=1`, `session_status=REVOKED`, `raw_password_match_count=0`
  - Cleanup: `deleted_sessions=1`, `deleted_credentials=1`, `deleted_memberships=1`, `deleted_subjects=1`, `deleted_tenants=1`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1811 passed, 1 warning`
  - Statement coverage: `98.21%`
  - Branch coverage: `94.50%`
  - Protected OA user-login PostgreSQL smoke remains skipped by default unless
    `NEX_OA_USER_LOGIN_POSTGRES_SMOKE=1` is set.

## Next

Slice 0255 can wire the AE API browser login facade to delegate
employee id/password verification to OA instead of issuing the current mock
session locally.
