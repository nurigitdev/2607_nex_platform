# Slice 0249: AE Auth Session Facade OA-Backed Cookie Wiring

## Scope

Wire the AE auth facade to the OA session client while preserving mock-mode
local regression behavior.

## Implemented

- Added `NEX_AE_AUTH_SESSION_MODE` with supported values `mock` and `oa`.
- Kept `mock` as the default for existing local tests.
- Added OA mode to AE auth routes:
  - Login delegates to OA session issue.
  - The HttpOnly browser cookie stores the opaque OA session id.
  - Current-session delegates cookie validation to OA introspection.
  - Logout delegates cookie revocation to OA, then deletes the cookie.
- Added OA mode to AE facade route auth so protected routes can derive
  browser-user owner scope from OA introspection.
- Added conversion from OA `oa_browser_session.v1` snapshots to AE
  `UserClaims` without exposing raw user tokens, service credentials, passwords,
  database URLs, or cookie values in JSON responses.

## Behavior

- `NEX_AE_AUTH_SESSION_MODE=mock` keeps the existing mock-token path.
- `NEX_AE_AUTH_SESSION_MODE=oa` makes the cookie value an opaque OA session id.
- Invalid, missing, inactive, expired, or revoked OA sessions fail AE auth with
  safe problem JSON.
- Missing required user scopes are still reported as `TOKEN_SCOPE_MISSING`.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ae_auth_sessions.py tests/test_nex_ae_route_auth.py tests/test_nex_ae_oa_session_client.py -q`
  - Result: `21 passed, 1 warning`
- Full regression and quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1761 passed, 1 warning`
  - Statement coverage: `98.11%`
  - Branch coverage: `94.24%`
