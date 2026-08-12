# Slice 0253: OA User Login API Foundation

## Scope

Add the OA-owned employee id/password login API foundation. This slice composes
the local credential registry from Slice 0252 with the OA user-session issuer
from Slice 0243. It does not move AE browser login to the OA-backed flow yet.

## Implemented

- Added `nex_oa.user_login.OaUserLoginService`.
- Added the protected OA endpoint:
  - `POST /internal/v1/auth/user-login`
- The login request accepts only:
  - `tenant_id`
  - `employee_id`
  - `password`
  - `requested_scopes`
  - `ttl_seconds`
- Successful login verifies the credential, maps the credential subject ref to
  the session issue request, and returns the existing browser-safe OA session
  issue response shape.
- Failed credential verification, inactive credentials, membership failures,
  and session issuance failures are mapped to problem JSON without exposing
  credential material.
- Registered the login service in the `nex-oa` app using the same runtime
  credential and session registries.

## Security Boundary

- The route is service-token protected and intended for the AE API facade.
- Raw passwords are used only for the verification call.
- Login responses do not include raw passwords, password hashes, credential
  snapshots, service credentials, cookie values, or database URLs.
- Unsupported fields are rejected; sensitive unsupported fields such as
  `password_hash`, API keys, tokens, cookies, authorization headers, and
  provider secrets return a private-payload error.
- The response preserves the OA session issue contract and sets
  `metadata.password_verified=true`.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_oa_user_login.py tests/test_nex_oa_credentials.py tests/test_nex_oa_sessions.py -q`
  - Result: `43 passed, 1 warning`
- User-login module coverage:
  `./.venv/bin/pytest tests/test_nex_oa_user_login.py --cov=nex_oa.user_login --cov-branch --cov-report=term-missing -q`
  - Result: `8 passed, 1 warning`; `nex_oa.user_login` at 100% statement and branch coverage.
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1804 passed, 1 warning`
  - Statement coverage: `98.19%`
  - Branch coverage: `94.48%`

## Next

Slice 0254 should exercise the full seed/login/session/readback path against
the real `nex_oa_test` PostgreSQL database with protected smoke evidence.
