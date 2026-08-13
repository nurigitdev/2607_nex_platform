# Slice 0262: AE Web Credential-Login Browser Smoke Boundary

## Scope

Define the protected browser smoke boundary for AE Web credential login before
adding an execution runner. The boundary must be explicit about required test
inputs, PostgreSQL proof, browser config safety, and redacted evidence.

## Implemented

- Added `scripts/smoke/run_ae_web_credential_login_browser_smoke_boundary.py`.
- The boundary is skipped by default and activates only with:
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1`
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_WEB_URL`
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_AE_API_BASE_URL`
  - `NEX_AE_TEST_DATABASE_URL`
  - `NEX_OA_TEST_DATABASE_URL`
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_TENANT_ID`
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_EMPLOYEE_ID`
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PASSWORD`
- The required phases cover static shell readiness, safe fetch runtime config,
  AE auth facade readiness, AE/OA migration proof, OA credential availability,
  browser form submit, active session readback, route guard allow proof, logout
  revocation readback, and redaction.
- Browser config validation rejects server-only keys such as DB URLs, tokens,
  cookies, provider endpoints, and passwords.
- Added the boundary to the default quality gate in skipped mode.
- Added regression coverage for default skip, required-env fail, non-test
  profile rejection, PASS projection, browser config rejection, config loading,
  redaction guard, evidence writing, CLI output, and docs/quality wiring.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_boundary.py -q`
  - Result: `10 passed`
- Runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_boundary.py --cov=run_ae_web_credential_login_browser_smoke_boundary --cov-branch --cov-report=term-missing -q`
  - Result: `10 passed`; 100% statement and branch coverage for the new runner.
- AE Web static regression:
  `./.venv/bin/pytest tests/test_nex_ae_web_static.py -q`
  - Result: `12 passed`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1836 passed, 1 warning`
  - Coverage: statement `98.24%`, branch `94.59%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
  - Default quality smoke summary includes:
    `ae_web_credential_login_browser_boundary=skipped reason=NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE boundary=pass phases=10`

## Next

Slice 0263 can add a deterministic browser-harness smoke runner that consumes
this boundary and the Slice 0261 fake-fetch harness without opening live
network connections by default.
