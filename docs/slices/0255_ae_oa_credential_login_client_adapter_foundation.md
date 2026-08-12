# Slice 0255: AE OA Credential-Login Client Adapter Foundation

## Scope

Extend the AE-to-OA auth client so AE API can delegate company employee id plus
password login to OA. This slice adds the adapter surface only; the public AE
browser login facade remains wired to the existing mode behavior until the next
slice.

## Implemented

- Added `HttpOaUserSessionClient.login_with_credentials(...)`.
- Added `oa_user_login_payload(...)` to map AE credential-login input to OA's
  `POST /internal/v1/auth/user-login` request shape.
- Preserved existing OA session issue, introspection, and revocation methods.
- Added operation-specific user-login timeout/unavailable/invalid-response
  error mapping while keeping the existing session-client error namespace for
  older calls.
- Kept the default OA base URL, service token, and timeout env contract shared:
  - `NEX_OA_BASE_URL`
  - `NEX_AE_TO_OA_SERVICE_TOKEN`
  - `NEX_AE_OA_SESSION_TIMEOUT_SECONDS`

## Security Boundary

- AE sends the raw password only in the service-to-service request body to OA.
- The adapter does not log, persist, or return the raw password.
- Transport/problem errors do not include the submitted password.
- `employee_id` or `login_identifier` is accepted as the login alias; downstream
  session ownership still depends on OA's returned stable `oa.user` subject ref.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ae_oa_session_client.py -q`
  - Result: `8 passed`
- Client module coverage:
  `./.venv/bin/pytest tests/test_nex_ae_oa_session_client.py --cov=nex_ae_api.oa_session_client --cov-branch --cov-report=term-missing -q`
  - Result: `8 passed`; `nex_ae_api.oa_session_client` at 100% statement and branch coverage.
- Time-stability regression hardening:
  `./.venv/bin/pytest tests/test_nex_oa_sessions.py::test_session_record_helpers_are_deterministic_and_validate_shape tests/test_nex_ae_oa_session_client.py -q`
  - Result: `9 passed`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1814 passed, 1 warning`
  - Coverage: statement `98.21%`, branch `94.51%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`

## Next

Slice 0256 should wire `POST /api/v1/auth/session/login` in OA mode to call
`login_with_credentials(...)` and store only the returned OA session id in the
HttpOnly browser cookie.
