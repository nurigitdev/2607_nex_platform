# Slice 0248: AE OA Session Client Adapter Foundation

## Scope

Add the AE-side client boundary for OA-backed browser sessions before changing
the AE auth facade runtime behavior.

## Implemented

- Added `nex_ae_api.oa_session_client.HttpOaUserSessionClient`.
- Added client methods for OA session issue, introspection, and revocation:
  - `POST /internal/v1/auth/user-sessions/issue`
  - `POST /internal/v1/auth/user-sessions/introspect`
  - `POST /internal/v1/auth/user-sessions/{session_id}/revoke`
- Added default configuration via:
  - `NEX_OA_BASE_URL`
  - `NEX_AE_TO_OA_SERVICE_TOKEN`
  - `NEX_AE_OA_SESSION_TIMEOUT_SECONDS`
- Added request validation, service-token propagation, trace/request-id
  propagation, timeout handling, problem response mapping, invalid JSON
  handling, and session-id path quoting.

## Deferred

- AE auth routes continue to default to mock cookie behavior until Slice 0249.
- PostgreSQL end-to-end smoke execution is deferred to Slice 0250, after the AE
  auth facade uses the OA-backed adapter.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ae_oa_session_client.py -q`
  - Result: `5 passed`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1756 passed, 1 warning`
  - Coverage: statement `98.13%`, branch `94.22%`
  - Contract validation: `pass` with 49 schemas, 78 examples, 54 negative
    examples, and 7 OpenAPI specs.
