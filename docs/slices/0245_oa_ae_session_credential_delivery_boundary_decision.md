# Slice 0245: OA-AE Session Credential Delivery Boundary Decision

## Scope

Freeze how OA-issued sessions will be delivered to browser users before adding
introspection and revocation.

## Decision

- OA owns membership-backed session issuance, session persistence, session
  introspection, and session revocation.
- AE owns browser login facade behavior, HttpOnly cookie set/delete, route-guard
  introspection calls, and browser-safe session projection.
- The selected delivery mode is
  `ae_http_only_cookie_with_oa_session_id`.
- The browser receives a safe session snapshot, not a raw user token.
- AE stores only an opaque OA session id in the browser cookie.

## Implemented

- Added protected endpoint:
  `GET /internal/v1/auth/session-credential-delivery-boundary`.
- Added a safe decision report with cookie policy, ownership split, forbidden
  payload classes, and the next delegation sequence.
- Updated the OA README and Slice index.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_oa_credential_delivery.py tests/test_nex_oa_auth_boundary.py -q`
  - Result: `6 passed, 1 warning`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1744 passed, 1 warning`
  - Coverage: statement `98.06%`, branch `94.14%`
  - Contract validation: `pass` with 49 schemas, 78 examples, 54 negative
    examples, and 7 OpenAPI specs.
