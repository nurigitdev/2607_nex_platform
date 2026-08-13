# Slice 0261: AE Web Credential-Login Browser Harness Foundation

## Scope

Add a deterministic browser-side harness for the AE Web credential-login flow.
The harness should prove the browser request sequence and authenticated route
guard behavior without using live network calls, PostgreSQL, raw cookies, or
server-only credentials.

## Implemented

- Added `apps/nex-ae-web/src/credentialLoginHarness.js`.
- The harness requires an injected fake `fetch` and executes:
  - current session read through `/api/v1/auth/session`
  - credential login through `/api/v1/auth/session/login`
  - authenticated runtime composition
  - session route guard projection
  - logout through `/api/v1/auth/session/logout`
- Added safe evidence summaries for runtime config, credential surface, session
  state, session client, bootstrap state, route guard, login request metadata,
  and fetch calls.
- The login body may carry the raw password to the AE facade, but the harness
  result redacts request bodies and fails if the raw password appears in the
  returned evidence.
- Added Node regression tests for success, input validation, HTTP 401/503
  boundaries, summary validation, and secret-leak detection.
- Added Python static guardrails so the harness stays mock-only and browser
  safe.

## Evidence

- AE Web Node regression:
  `npm --prefix apps/nex-ae-web test`
  - Result: `76 passed`
- AE Web static regression:
  `./.venv/bin/pytest tests/test_nex_ae_web_static.py -q`
  - Result: `12 passed`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1826 passed, 1 warning`
  - Coverage: statement `98.23%`, branch `94.53%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
  - Default quality smoke summary includes:
    `ae_web_credential_login_postgres_smoke=skipped reason=NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE`

## Next

After Slice 0261, the next browser slice can either wire this harness into a
Playwright-style protected browser smoke runner or continue hardening credential
session expiry and logout UX.
