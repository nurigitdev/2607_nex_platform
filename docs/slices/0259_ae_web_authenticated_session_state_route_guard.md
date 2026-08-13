# Slice 0259: AE Web Authenticated Session State Route Guard

## Scope

Make post-login AE Web behavior explicit: protected AE facade routes should show
whether they are allowed, blocked, or running in mock preview, and browser
payload owner scope should follow authenticated OA session claims after login.

## Implemented

- Added `apps/nex-ae-web/src/sessionRouteGuard.js`.
- Added a visible `session-route-guard-summary` under the credential-login
  panel.
- Runtime diagnostics now include `route_guard_status` and a safe
  `session_route_guard` summary.
- `main.js` now rebuilds upload/document owner scope from authenticated session
  claims so protected route payloads are claim-derived after login.
- Added Node and Python regression coverage for allowed, blocked, mock-preview,
  summary validation, diagnostics wiring, and static guard anchors.

## Evidence

- Node AE Web tests:
  `npm --prefix apps/nex-ae-web test`
  - Result: `72` tests passed across `17` suites.
- Targeted Python regression:
  `./.venv/bin/pytest tests/test_nex_ae_web_static.py tests/test_ae_web_static_browser_smoke.py -q`
  - Result: `19 passed`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1821 passed, 1 warning`
  - Coverage: statement `98.22%`, branch `94.51%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
  - Static browser smoke:
    `ae_web_static_browser_smoke=pass slice=Slice_0227 anchors=17 url=http://127.0.0.1:5227/`

## Next

Slice 0260 should add protected PostgreSQL smoke evidence for the credential
login plus AE Web authenticated route-guard path against real test databases.
