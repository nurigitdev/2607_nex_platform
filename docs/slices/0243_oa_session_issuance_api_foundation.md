# Slice 0243: OA Session Issuance API Foundation

## Scope

Move browser session authority toward OA by adding a membership-backed session
issuance API and persistence adapter. AE still owns browser cookie composition
for now.

## Implemented

- Added `oa_user_sessions` to the `nex-oa` migration set.
- Added in-memory and SQLAlchemy OA session registries.
- Added service-token protected routes:
  - `POST /internal/v1/auth/user-sessions/issue`
  - `GET /internal/v1/auth/user-sessions/{session_id}`
- Session issuance requires an existing active OA tenant membership.
- Requested scopes must be a subset of the membership scopes.
- Responses include a browser-session snapshot but no raw access token, cookie,
  password, service credential, or external provider payload.

## Boundary

- OA now owns membership-backed user-session issuance and session readback.
- AE remains responsible for browser runtime composition and cookie setting
  until delegation wiring is explicitly added.
- 0244 will exercise the same route/store boundary against `nex_oa_test`.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_oa_sessions.py tests/test_nex_oa_memberships.py tests/test_database_schema_foundation.py -q`
  - Result: `36 passed, 1 warning`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1734 passed, 1 warning`
  - Coverage: statement `98.05%`, branch `94.11%`
  - Contract validation: `pass` with 49 schemas, 78 examples, 54 negative
    examples, and 7 OpenAPI specs.
