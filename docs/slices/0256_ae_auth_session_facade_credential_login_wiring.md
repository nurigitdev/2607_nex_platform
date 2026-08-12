# Slice 0256: AE Auth Session Facade Credential-Login Wiring

## Scope

Switch AE's OA-backed browser login facade from direct OA session issuance to
company employee id plus password login. The default mock mode remains available
for local regression, but `NEX_AE_AUTH_SESSION_MODE=oa` now delegates
credential verification to OA and stores only the returned opaque OA session id
in the HttpOnly browser cookie.

## Implemented

- Added mode-aware login request normalization:
  - mock mode keeps the existing `user_id` or `login_hint` local token flow.
  - OA mode accepts `employee_id`, `login_identifier`, or `login_hint` plus
    `password`.
  - OA mode maps `scopes` or `requested_scopes` to OA requested scopes and
    rejects ambiguous scope aliases.
- Updated `issue_browser_session(...)` in OA mode to call
  `OaUserSessionClient.login_with_credentials(...)`.
- Kept OA introspection and revocation behavior unchanged for current-session,
  route guards, and logout.
- Updated the protected AE-OA PostgreSQL smoke runner so the optional test DB
  smoke seeds an OA local credential, logs in through AE with employee/password,
  verifies the OA session, and cleans up credential rows.
- Updated the AE OpenAPI login request shape to document the OA credential-login
  input while preserving mock-mode fields.

## Security Boundary

- AE accepts the raw password only at the browser login facade and forwards it
  to OA through the service-to-service user-login call.
- AE does not put the password into the browser session payload, cookie,
  operation evidence, or returned errors.
- Downstream owner scope still comes from the OA `oa.user` subject ref returned
  in the browser session, not from the submitted `employee_id`.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ae_auth_sessions.py tests/test_nex_ae_oa_session_client.py tests/test_ae_oa_auth_postgres_smoke.py -q`
  - Result: `31 passed, 1 warning`
- Focused coverage:
  `./.venv/bin/pytest tests/test_nex_ae_auth_sessions.py tests/test_ae_oa_auth_postgres_smoke.py --cov=nex_ae_api.auth_sessions --cov=run_ae_oa_auth_postgres_smoke --cov-branch --cov-report=term-missing -q`
  - Result: `23 passed, 1 warning`
  - Coverage: `nex_ae_api.auth_sessions` 96%,
    `run_ae_oa_auth_postgres_smoke.py` 99%, combined 98%
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1815 passed, 1 warning`
  - Coverage: statement `98.21%`, branch `94.50%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
- Protected PostgreSQL smoke:
  `NEX_AE_OA_AUTH_POSTGRES_SMOKE=1 ... ./scripts/smoke/run_ae_oa_auth_postgres_smoke.py --summary`
  - Result:
    `ae_oa_auth_postgres_smoke=pass profile=test ae_db=NEX_AE_TEST_DATABASE_URL oa_db=NEX_OA_TEST_DATABASE_URL oa_session_status=REVOKED`

## Next

Slice 0257 should update the AE Web login surface, if needed, so the browser
form sends the company employee id and password fields expected by OA mode.
