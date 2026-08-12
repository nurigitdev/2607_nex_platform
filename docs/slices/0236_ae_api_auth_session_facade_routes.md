# Slice 0236: AE API Auth Session Facade Routes

## Scope

Slice 0236 adds the AE API auth session facade routes needed by the AE Web
session client added in Slice 0234.

Implemented:

- Added `services/nex-ae-api/nex_ae_api/auth_sessions.py`.
- Registered the auth session routes in `services/nex-ae-api/nex_ae_api/main.py`.
- Added `tests/test_nex_ae_auth_sessions.py`.
- Updated `contracts/openapi/nex-ae-api.openapi.yaml` with the auth session
  route surface.
- Updated the AE API README and working-doc slice index.

Routes:

- `GET /api/v1/auth/session`
- `POST /api/v1/auth/session/login`
- `POST /api/v1/auth/session/logout`

## Boundary

The facade returns the existing `oa_browser_session.v1` safe snapshot shape.
It does not return raw access tokens, passwords, service credentials, provider
endpoints, database URLs, or storage paths.

The mock login route issues a local user token only into an HttpOnly same-site
cookie. Current-session and logout routes validate either the Authorization
header or that cookie, then return safe ACTIVE/REVOKED browser session
snapshots. This keeps the browser JSON contract stable while leaving room for a
real OA session/SSO implementation later.

This Slice does not require PostgreSQL smoke evidence because it adds stateless
AE API facade routes and reuses the existing mock user token verifier.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_auth_sessions.py tests/test_nex_ae_auth_guard.py tests/test_nex_runtime_auth.py -q
```

Contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
42 passed, 1 warning in 1.07s
```

Observed contract validation:

```text
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
```

Observed full quality gate:

```text
1696 passed, 1 warning in 58.17s
statement_coverage=98.04% threshold=95.00%
branch_coverage=93.93% threshold=85.00%
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
