# Slice 0265: AE Web Credential-Login Browser Live Smoke Execution

## Scope

Add the protected execution runner for the AE Web credential-login browser
smoke. The default quality gate keeps this runner skipped, but an operator can
enable it with `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1` to prove the login
flow against real AE and OA PostgreSQL test databases.

## Implemented

- Added `scripts/smoke/run_ae_web_credential_login_browser_live_smoke.py`.
- The runner emits `ae_web_credential_login_browser_live_smoke.v1` evidence.
- Enabled execution requires the Slice 0262 protected boundary to pass before
  any child smoke runs.
- Enabled execution runs:
  - Slice 0264 readiness evidence.
  - AE credential-login PostgreSQL smoke against `NEX_AE_TEST_DATABASE_URL` and
    `NEX_OA_TEST_DATABASE_URL`.
  - Slice 0263 deterministic browser harness smoke.
- Browser smoke password input now propagates into the PostgreSQL
  credential-login smoke through:
  - `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PASSWORD`
  - `NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_PASSWORD`
  - `NEX_AE_OA_AUTH_POSTGRES_SMOKE_PASSWORD`
- PASS evidence records:
  - AE and OA database env names.
  - Redacted database URLs.
  - Migration evidence.
  - AE marker write/readback.
  - OA credential/session readback.
  - Password verification status.
  - Browser route guard `allowed`.
  - Logout and DB session revocation readback.
  - Cleanup observations.
- Added regression coverage for skipped, pass, boundary failure, readiness
  failure, credential failure/skipped, harness failure, inconsistent PASS,
  redaction, CLI output, docs, and quality-gate wiring.
- Added the live runner to the default quality gate in skipped mode.

## Protected Execution Env

Use test-profile PostgreSQL databases only:

```bash
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PROFILE=test
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_WEB_URL=http://127.0.0.1:5227
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_AE_API_BASE_URL=http://127.0.0.1:8003
NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:...@127.0.0.1:5432/nex_ae_test
NEX_OA_TEST_DATABASE_URL=postgresql+psycopg://nex_oa_user:...@127.0.0.1:5432/nex_oa_test
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_TENANT_ID=tenant-slice-0265
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_EMPLOYEE_ID=EMP-0265
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PASSWORD=...
```

Then run:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_live_smoke.py --summary
```

## Evidence

- Default summary:
  `./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_live_smoke.py --summary`
  - Result:
    `ae_web_credential_login_browser_live_smoke=skipped reason=NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE`
- Enabled PostgreSQL smoke summary:
  `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_live_smoke.py --summary`
  - Result:
    `ae_web_credential_login_browser_live_smoke=pass profile=test ae_db=NEX_AE_TEST_DATABASE_URL oa_db=NEX_OA_TEST_DATABASE_URL route_guard=allowed oa_session_status=REVOKED live_db=true`
- Targeted regression:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_live_smoke.py tests/test_ae_credential_login_postgres_smoke.py tests/test_ae_oa_auth_postgres_smoke.py -q`
  - Result: `25 passed, 1 warning`
- Runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_live_smoke.py --cov=run_ae_web_credential_login_browser_live_smoke --cov-branch --cov-report=term-missing -q`
  - Result: `11 passed, 1 warning`; 100% statement and branch coverage for the
    new runner.
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1866 passed, 1 warning`
  - Coverage: statement `98.27%`, branch `94.64%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
  - Default quality smoke summary includes:
    `ae_web_credential_login_browser_live_smoke=skipped reason=NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE`

## Next

Slice 0266 should harden the live evidence with explicit PostgreSQL connection
metadata, child-smoke status closure, and cleanup/readback invariants so enabled
smoke output is easier to audit after a short run.
