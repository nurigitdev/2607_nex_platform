# Slice 0247: OA Session Revocation API Foundation

## Scope

Add the internal OA endpoint that AE can call to revoke an opaque OA session id
without receiving or storing raw user credentials.

## Implemented

- Added protected endpoint:
  `POST /internal/v1/auth/user-sessions/{session_id}/revoke`.
- Added in-memory and SQLAlchemy session registry revocation paths.
- Added an idempotent revocation response with `revoked`, `already_revoked`,
  `inactive_reason`, `revoked_at`, and a browser-safe session snapshot.
- Wired revocation into introspection behavior so revoked sessions immediately
  return `active=false` with `inactive_reason=revoked`.
- Hardened the protected OA PostgreSQL session smoke runner to exercise
  issue/readback/introspection/revocation/revoked-introspection plus DB status
  observation.

## Behavior

- Existing sessions are updated to `REVOKED`, with `revoked_at` and `updated_at`
  set by OA.
- Repeated revocation is safe and keeps the original `revoked_at`.
- Missing sessions return `revoked=false` and `inactive_reason=not_found`.
- Responses continue to exclude raw user tokens, service credentials, passwords,
  database URLs, and cookie values.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_oa_sessions.py tests/test_oa_session_postgres_smoke.py tests/test_nex_oa_credential_delivery.py -q`
  - Result: `25 passed, 1 warning`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1751 passed, 1 warning`
  - Coverage: statement `98.13%`, branch `94.21%`
  - Contract validation: `pass` with 49 schemas, 78 examples, 54 negative
    examples, and 7 OpenAPI specs.
