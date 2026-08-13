# AE Web Credential-Login Browser Smoke Runbook

## Purpose

Use this runbook when an operator needs to prove the AE Web credential-login
browser path with real PostgreSQL test databases. Default quality-gate execution
keeps the protected runners skipped. Enabled execution must use only
`*_test` databases.

## Required Environment

```bash
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PROFILE=test
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_WEB_URL=http://127.0.0.1:5227
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_AE_API_BASE_URL=http://127.0.0.1:8003
NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:...@127.0.0.1:5432/nex_ae_test
NEX_OA_TEST_DATABASE_URL=postgresql+psycopg://nex_oa_user:...@127.0.0.1:5432/nex_oa_test
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_TENANT_ID=tenant-slice-smoke
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_EMPLOYEE_ID=EMP-SMOKE
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PASSWORD=...

# Optional for same-origin browser execution through the AE Web dev server.
# Browser runtime config should still use ae_base_url=/ae-api.
AE_API_PROXY_TARGET=http://127.0.0.1:8003

# Optional when Playwright browser downloads are not installed.
NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome
```

## Commands

First check operator profile wiring:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_operator_profile.py --summary
```

Then check the same-origin dev-server boundary:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_same_origin_runtime_boundary.py --summary
```

Check Playwright readiness before running a browser-driven smoke:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_playwright_readiness.py --summary
```

Run the protected live smoke:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_live_smoke.py --summary
```

Run the hardened PostgreSQL evidence check:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_postgres_evidence_hardening.py --summary
```

## Expected Results

- Default profile:
  - `ae_web_credential_login_browser_operator_profile=pass mode=default`
  - `ae_web_same_origin_runtime_boundary=pass proxy=/ae-api`
  - `ae_web_playwright_readiness=pass dependency=@playwright/test`
  - `ae_web_credential_login_browser_live_smoke=skipped`
  - `ae_web_credential_login_browser_postgres_evidence_hardening=skipped`
- Protected profile:
  - `ae_web_credential_login_browser_live_smoke=pass ... live_db=true`
  - `ae_web_credential_login_browser_postgres_evidence_hardening=pass ... issues=0`

## Guardrails

- Do not use dev databases for protected smoke execution.
- Keep `AE_API_PROXY_TARGET` server-side; browser runtime config should expose
  only the same-origin `/ae-api` base path.
- Do not store raw passwords, DB URLs, cookies, tokens, or provider endpoints in
  evidence files.
- Treat a skipped protected runner as "not executed", not as live validation.
- Prefer the hardening runner result as the final pass/fail signal for the
  PostgreSQL-backed credential-login browser path.
