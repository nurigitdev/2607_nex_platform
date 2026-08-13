# Slice 0267: AE Web Credential-Login Browser Operator Profile

## Scope

Add an operator runbook and profile checker for the protected AE Web
credential-login browser smoke path. This slice does not open PostgreSQL
connections by itself; it verifies the env, command order, redaction policy, and
quality-gate wiring needed to run Slice 0265 and Slice 0266 safely.

## Implemented

- Added `docs/runbooks/ae_web_credential_login_browser_smoke.md`.
- Added `scripts/smoke/run_ae_web_credential_login_browser_operator_profile.py`.
- The checker emits `ae_web_credential_login_browser_operator_profile.v1`.
- Default mode verifies the protected runners remain explicit/skipped by
  default.
- Protected mode validates:
  - required env names are present.
  - `NEX_AE_TEST_DATABASE_URL` targets a `*_test` database.
  - `NEX_OA_TEST_DATABASE_URL` targets a `*_test` database.
  - profile is `test`.
  - runbook contains live smoke and hardening commands.
  - evidence excludes raw DB URLs, password, tenant id, and employee id.
- Added the checker to the default quality gate before live/hardening runners.
- Added regression coverage for default mode, protected env, missing env,
  non-test DB URLs, non-test profile, missing docs/wiring, redaction, output,
  CLI, and docs/quality wiring.

## Evidence

- Default summary:
  `./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_operator_profile.py --summary`
  - Result:
    `ae_web_credential_login_browser_operator_profile=pass mode=default env=0/7 order=3`
- Protected profile summary:
  `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_operator_profile.py --summary`
  - Result:
    `ae_web_credential_login_browser_operator_profile=pass mode=protected env=7/7 order=3`
- Targeted regression:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_operator_profile.py -q`
  - Result: `8 passed`
- Runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_operator_profile.py --cov=run_ae_web_credential_login_browser_operator_profile --cov-branch --cov-report=term-missing -q`
  - Result: `8 passed`; 100% statement and branch coverage for the new runner.
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1884 passed, 1 warning`
  - Coverage: statement `98.29%`, branch `94.71%`
  - Contract validation: `pass`; schemas `50`, examples `79`,
    negative examples `55`, OpenAPI `7`
  - Default quality smoke summary includes:
    `ae_web_credential_login_browser_operator_profile=pass mode=default env=0/7 order=3`

## Next

Slice 0268 should audit the AE Web dev-server and same-origin runtime boundary
before Playwright is added, especially `/ae-api` routing, cookie safety, and
runtime config constraints.
