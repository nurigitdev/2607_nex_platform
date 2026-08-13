# Slice 0260: AE Web Credential-Login PostgreSQL Smoke Evidence

## Scope

Add protected smoke evidence for the AE Web credential-login surface against the
real AE and OA PostgreSQL test databases. This verifies the browser login
surface, AE credential-login facade, OA user-login persistence, and AE Web route
guard evidence as one protected path.

## Implemented

- Added `scripts/smoke/run_ae_web_credential_login_postgres_smoke.py`.
- The runner wraps the Slice 0257 AE credential-login PostgreSQL smoke so the
  DB evidence is real, then projects AE Web-specific evidence:
  - credential-login form anchors
  - credential payload builder presence
  - root password allowed only for login submit
  - session route guard schema and protected route count
  - owner scope source after login as `session-claims`
- Added the runner to the default quality gate in skipped mode.
- Added the runner to the PostgreSQL test smoke suite as the
  `ae_web_credential_login` stage.
- Added regression tests for skip, pass projection, source failure, source
  skip, redaction, CLI summary, and suite integration.

## Execution

Protected smoke uses:

- `NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE=1`
- `NEX_AE_TEST_DATABASE_URL`
- `NEX_OA_TEST_DATABASE_URL`
- Optional scoped ids:
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE_TENANT_ID`
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE_SUBJECT_ID`
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE_EMPLOYEE_ID`

The projected evidence keeps raw DB URLs, tenant ids, subject ids, employee ids,
passwords, and cookie material out of committed summaries.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_postgres_smoke.py tests/test_ae_credential_login_postgres_smoke.py tests/test_smoke_helpers.py::test_postgres_test_smoke_suite_reports_pass_without_leaking_secret tests/test_smoke_helpers.py::test_postgres_test_smoke_suite_skips_by_default -q`
  - Result: `10 passed, 1 warning`
- Runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_postgres_smoke.py --cov=run_ae_web_credential_login_postgres_smoke --cov-branch --cov-report=term-missing -q`
  - Result: `4 passed, 1 warning`; 100% statement and branch coverage for the new runner.
- Protected PostgreSQL smoke against `nex_ae_test` and `nex_oa_test`:
  `NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_ae_web_credential_login_postgres_smoke.py --summary`
  - Result:
    `ae_web_credential_login_postgres_smoke=pass profile=test ae_db=NEX_AE_TEST_DATABASE_URL oa_db=NEX_OA_TEST_DATABASE_URL route_guard=allowed oa_credential_count=1 oa_session_status=REVOKED`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1825 passed, 1 warning`
  - Coverage: statement `98.23%`, branch `94.53%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
  - Default quality smoke summary includes:
    `ae_web_credential_login_postgres_smoke=skipped reason=NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE`

## Next

After Slice 0260, the next slice can move toward browser-level smoke automation
or continue with OA credential lifecycle hardening.
