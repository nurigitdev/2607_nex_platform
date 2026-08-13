# Slice 0270: AE Web Credential-Login Playwright PostgreSQL Smoke

## Scope

Add a protected Playwright browser smoke for the AE Web credential-login path.
When enabled, this smoke must connect to the real AE and OA PostgreSQL test
databases, run migrations, seed an OA employee credential, drive the browser
login/logout flow, verify persisted OA session revocation, and clean up smoke
rows.

## Implemented

- Added `apps/nex-ae-web/scripts/runCredentialLoginPlaywrightSmoke.mjs`.
- Added npm script `smoke:credential-login-playwright`.
- The Node smoke uses Playwright Chromium to:
  - inject safe fetch-mode runtime config with `ae_base_url=/ae-api`;
  - fill tenant id, employee id, and password into the AE Web form;
  - submit login through `/ae-api/api/v1/auth/session/login`;
  - verify route guard `allowed`;
  - submit logout through `/ae-api/api/v1/auth/session/logout`;
  - verify the route guard returns to `blocked`;
  - keep raw passwords, cookies, tokens, DB URLs, and provider endpoints out of
    evidence.
- Added
  `scripts/smoke/run_ae_web_credential_login_playwright_postgres_smoke.py`.
- The Python protected runner:
  - skips by default until
    `NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE=1`;
  - requires profile `test`;
  - runs AE and OA migrations against `*_test` database URLs;
  - seeds OA subject, membership, and local credential rows;
  - starts AE API and AE Web on temporary local ports;
  - configures the AE Web dev proxy with server-side `AE_API_PROXY_TARGET`;
  - runs the Playwright smoke;
  - reads back OA session status from PostgreSQL;
  - deletes AE marker and OA smoke rows after execution.
- Added the runner to the default quality gate in skipped mode.
- Added Node and Python regression coverage for pass/fail, redaction, parsing,
  cleanup, session readback, CLI, package, docs, and quality-gate wiring.

## Evidence

- Default quality-gate summary:
  `./.venv/bin/python scripts/smoke/run_ae_web_credential_login_playwright_postgres_smoke.py --summary`
  - Expected when not enabled:
    `ae_web_credential_login_playwright_postgres_smoke=skipped reason=NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE`
- Protected execution summary:
  `NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_ae_web_credential_login_playwright_postgres_smoke.py --summary`
  - Expected:
    `ae_web_credential_login_playwright_postgres_smoke=pass ... live_db=true browser=playwright`
- Node regression:
  `npm --prefix apps/nex-ae-web test`
- Python runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_playwright_postgres_smoke.py --cov=run_ae_web_credential_login_playwright_postgres_smoke --cov-branch --cov-report=term-missing -q`

## Notes

If Playwright browser downloads are unavailable, set
`NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome` or another
local Chrome/Chromium binary.
