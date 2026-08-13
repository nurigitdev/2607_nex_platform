# Slice 0266: AE Web Credential-Login Browser PostgreSQL Evidence Hardening

## Scope

Harden the Slice 0265 live smoke evidence so a short protected run still proves
real PostgreSQL test database execution, credential verification, session
revocation, cleanup, and redaction. The hardening runner is skipped by default
in the quality gate and only executes when the protected browser smoke env is
enabled.

## Implemented

- Added
  `contracts/schemas/service/nex_ae_web/credential_login_browser_live_smoke_evidence.v1.schema.json`.
- Added PASS and negative fixtures:
  - `contracts/examples/operations/ae_web_credential_login_browser_live_smoke_evidence.postgres_success.json`
  - `contracts/tests/negative/operations/ae_web_credential_login_browser_live_smoke_evidence.raw_database_url.json`
- Registered both fixtures in the contract example and negative indexes.
- Added
  `scripts/smoke/run_ae_web_credential_login_browser_postgres_evidence_hardening.py`.
- The hardening runner emits
  `ae_web_credential_login_browser_postgres_evidence_hardening.v1`.
- Enabled execution calls the Slice 0265 live runner and then validates:
  - PASS evidence contract schema.
  - exact AE/OA test DB env names.
  - migration service/profile/write-mode evidence.
  - AE marker readback.
  - OA credential/session readback.
  - password verification.
  - route guard `allowed`.
  - logout revocation readback.
  - cleanup counts.
  - all PASS checks are true.
  - redacted evidence only.
- Added the hardening runner to the default quality gate in skipped mode.
- Added regression coverage for skip, pass, live non-pass, schema failure,
  invariant failure, contract fixtures, redaction, helpers, CLI output, docs,
  and quality-gate wiring.

## Protected Execution Env

Use the same env as Slice 0265:

```bash
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PROFILE=test
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_WEB_URL=http://127.0.0.1:5227
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_AE_API_BASE_URL=http://127.0.0.1:8003
NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:...@127.0.0.1:5432/nex_ae_test
NEX_OA_TEST_DATABASE_URL=postgresql+psycopg://nex_oa_user:...@127.0.0.1:5432/nex_oa_test
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_TENANT_ID=tenant-slice-0266
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_EMPLOYEE_ID=EMP-0266
NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PASSWORD=...
```

Then run:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_postgres_evidence_hardening.py --summary
```

## Evidence

- Default summary:
  `./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_postgres_evidence_hardening.py --summary`
  - Result:
    `ae_web_credential_login_browser_postgres_evidence_hardening=skipped reason=NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE`
- Enabled PostgreSQL hardening summary:
  `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_postgres_evidence_hardening.py --summary`
  - Result:
    `ae_web_credential_login_browser_postgres_evidence_hardening=pass profile=test schema=ae_web_credential_login_browser_live_smoke.v1 route_guard=allowed oa_session_status=REVOKED issues=0`
- Targeted regression:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_postgres_evidence_hardening.py -q`
  - Result: `10 passed, 1 warning`
- Runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_postgres_evidence_hardening.py --cov=run_ae_web_credential_login_browser_postgres_evidence_hardening --cov-branch --cov-report=term-missing -q`
  - Result: `10 passed, 1 warning`; 100% statement and branch coverage for the
    new runner.
- Contract validation:
  `./.venv/bin/python scripts/quality/validate_contracts.py`
  - Result: `contract_validation=pass schemas=50 examples=79 negative_examples=55 openapi=7`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1876 passed, 1 warning`
  - Coverage: statement `98.28%`, branch `94.69%`
  - Contract validation: `pass`; schemas `50`, examples `79`,
    negative examples `55`, OpenAPI `7`
  - Default quality smoke summary includes:
    `ae_web_credential_login_browser_postgres_evidence_hardening=skipped reason=NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE`

## Next

Slice 0267 can move from credential-login browser evidence closure toward the
next AE Web/OA integration concern, such as login session lifecycle visibility,
operator-facing browser smoke instructions, or Playwright adoption if we decide
the dependency is worth adding.
