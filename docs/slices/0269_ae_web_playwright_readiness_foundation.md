# Slice 0269: AE Web Playwright Readiness Foundation

## Scope

Add the Playwright dependency and readiness checks required before a protected
browser-driven credential-login smoke can run. Default quality-gate execution
remains static and does not launch a browser or open PostgreSQL connections.

## Implemented

- Added `@playwright/test` to `apps/nex-ae-web/package.json`.
- Added `apps/nex-ae-web/package-lock.json`.
- Added `apps/nex-ae-web/scripts/runCredentialLoginPlaywrightReadiness.mjs`.
- Added npm script `smoke:playwright-readiness`.
- The Node readiness script verifies:
  - Playwright can be imported.
  - Chromium is the protected smoke browser profile.
  - browser launch is optional and controlled by
    `NEX_AE_WEB_PLAYWRIGHT_LAUNCH_CHECK=1` or `--launch-check`.
  - a system Chrome/Chromium binary can be supplied with
    `NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE`.
  - browser smoke must use the same-origin `/ae-api` path and test PostgreSQL
    databases when live execution is enabled.
- Added `scripts/smoke/run_ae_web_playwright_readiness.py`.
- The Python readiness checker verifies package/lock/script/test/runbook/
  quality-gate wiring without requiring installed npm dependencies by default.
- Added Node and Python regression coverage for pass, failure, redaction, CLI,
  optional launch-check, and docs/quality wiring branches.

## Evidence

- Playwright readiness summary:
  `./.venv/bin/python scripts/smoke/run_ae_web_playwright_readiness.py --summary`
  - Expected:
    `ae_web_playwright_readiness=pass dependency=@playwright/test mode=static launch=deferred`
- Installed dependency check:
  `./.venv/bin/python scripts/smoke/run_ae_web_playwright_readiness.py --require-installed --summary`
  - Expected:
    `ae_web_playwright_readiness=pass dependency=@playwright/test mode=installed launch=deferred`
- Optional launch check with a system Chrome binary:
  `NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node apps/nex-ae-web/scripts/runCredentialLoginPlaywrightReadiness.mjs --launch-check --summary`
- AE Web Node regression:
  `npm --prefix apps/nex-ae-web test`
- Python runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_playwright_readiness.py --cov=run_ae_web_playwright_readiness --cov-branch --cov-report=term-missing -q`

## Next

Slice 0270 should execute the protected Playwright browser smoke against AE/OA
test databases through the `/ae-api` same-origin dev-server proxy.
