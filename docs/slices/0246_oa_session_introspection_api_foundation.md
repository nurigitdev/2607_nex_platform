# Slice 0246: OA Session Introspection API Foundation

## Scope

Add the internal OA endpoint that AE can call to validate the opaque OA session
id stored in its HttpOnly browser cookie.

## Implemented

- Added protected endpoint:
  `POST /internal/v1/auth/user-sessions/introspect`.
- Added in-memory and SQLAlchemy session registry introspection paths.
- Added a browser-safe introspection response with `active`,
  `inactive_reason`, `tenant_ref`, `subject_ref`, and a safe session snapshot.
- Added request validation that rejects unsupported fields and credential-like
  payloads before lookup.
- Kept raw user tokens, service credentials, passwords, database URLs, and cookie
  values out of responses and test evidence.

## Behavior

- Existing `ACTIVE` sessions return `active=true` while `expires_at` remains in
  the future.
- `EXPIRED` and time-expired sessions return `inactive_reason=expired`.
- `REVOKED` sessions return `inactive_reason=revoked`.
- Missing sessions return `inactive_reason=not_found` without exposing
  ownership details.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_oa_sessions.py tests/test_nex_oa_credential_delivery.py -q`
  - Result: `15 passed, 1 warning`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1748 passed, 1 warning`
  - Coverage: statement `98.09%`, branch `94.15%`
  - Contract validation: `pass` with 49 schemas, 78 examples, 54 negative
    examples, and 7 OpenAPI specs.
