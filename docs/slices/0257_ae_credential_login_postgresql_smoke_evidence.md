# Slice 0257: AE Credential-Login PostgreSQL Smoke Evidence

## Scope

Add a dedicated protected smoke runner for the AE credential-login path against
the real PostgreSQL test databases. This slice makes the company employee id
plus password path explicit, instead of relying only on the broader AE-OA auth
smoke name.

## Implemented

- Added `scripts/smoke/run_ae_credential_login_postgres_smoke.py`.
- The runner enables and wraps the existing AE-OA auth PostgreSQL smoke with a
  credential-login-specific schema, env toggle, summary line, and evidence
  projection.
- Added credential-login observations:
  - AE endpoint: `POST /api/v1/auth/session/login`
  - OA endpoint: `POST /internal/v1/auth/user-login`
  - OA client operation sequence begins with `login_with_credentials`
  - password verification occurred in OA
  - browser cookie value remains an opaque OA session id
- Added regression tests for skip, pass projection, source failure mapping,
  redaction guards, CLI summary, and source-skip handling.
- Added the new smoke summary to `scripts/quality/run_quality_gate.sh`; it
  remains skipped by default unless explicitly enabled.
- Added the smoke to `run_postgres_test_smoke_suite.py` as the
  `ae_credential_login` stage so the all-service PostgreSQL smoke suite covers
  this path too.

## Execution

Protected smoke uses:

- `NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE=1`
- `NEX_AE_TEST_DATABASE_URL`
- `NEX_OA_TEST_DATABASE_URL`
- Optional scoped ids:
  - `NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_TENANT_ID`
  - `NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_SUBJECT_ID`
  - `NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_EMPLOYEE_ID`

The runner maps these to the underlying AE-OA smoke env names and keeps raw DB
URLs, tenant ids, subject ids, and employee ids out of projected evidence.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_ae_credential_login_postgres_smoke.py tests/test_ae_oa_auth_postgres_smoke.py -q`
  - Result: `14 passed, 1 warning`
- Runner coverage:
  `./.venv/bin/pytest tests/test_ae_credential_login_postgres_smoke.py --cov=run_ae_credential_login_postgres_smoke --cov-branch --cov-report=term-missing -q`
  - Result: `4 passed, 1 warning`; 100% statement and branch coverage for the new runner.
- Smoke-suite regression:
  `./.venv/bin/pytest tests/test_ae_credential_login_postgres_smoke.py tests/test_ae_oa_auth_postgres_smoke.py tests/test_smoke_helpers.py::test_postgres_test_smoke_suite_reports_pass_without_leaking_secret tests/test_smoke_helpers.py::test_postgres_test_smoke_suite_skips_by_default -q`
  - Result: `16 passed, 1 warning`
- Protected PostgreSQL smoke against `nex_ae_test` and `nex_oa_test`:
  `NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_ae_credential_login_postgres_smoke.py --summary`
  - Result:
    `ae_credential_login_postgres_smoke=pass profile=test ae_db=NEX_AE_TEST_DATABASE_URL oa_db=NEX_OA_TEST_DATABASE_URL oa_credential_count=1 oa_session_status=REVOKED`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1819 passed, 1 warning`
  - Coverage: statement `98.22%`, branch `94.51%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
  - Default quality smoke summary includes:
    `ae_credential_login_postgres_smoke=skipped reason=NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE`

## Next

Slice 0258 can update the AE Web login surface, if needed, so the browser form
sends the company employee id and password fields expected by OA mode.
