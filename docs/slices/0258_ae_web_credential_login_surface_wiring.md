# Slice 0258: AE Web Credential-Login Surface Wiring

## Scope

Wire the AE Web shell so the browser can collect the MVP company login shape:
tenant id, employee id, and password. This slice keeps the browser surface
mock-first, but makes the fetch-mode payload compatible with the AE auth facade
implemented in Slice 0256.

## Implemented

- Added `apps/nex-ae-web/src/credentialLoginSurface.js`.
- Added a `credential-login-panel` to the AE Web shell with tenant, employee id,
  password, login, logout, feedback, and safe summary anchors.
- Updated `sessionClient.login()` so a root `password` field is permitted only
  for login requests, while session snapshots and nested fields continue to
  reject password, token, service, database, provider, and secret material.
- Updated the static browser smoke anchor list to require the credential-login
  surface.
- Added Node and Python regression coverage for the credential-login request
  builder, summary redaction, session-client login payload, static anchors, and
  unsupported secret fields.

## Evidence

- Node AE Web tests:
  `npm --prefix apps/nex-ae-web test`
  - Result: `68` tests passed across `16` suites.
- Targeted Python regression:
  `./.venv/bin/pytest tests/test_nex_ae_web_static.py tests/test_ae_web_static_browser_smoke.py -q`
  - Result: `18 passed`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1820 passed, 1 warning`
  - Coverage: statement `98.22%`, branch `94.51%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
  - Static browser smoke:
    `ae_web_static_browser_smoke=pass slice=Slice_0227 anchors=16 url=http://127.0.0.1:5227/`

## Next

Slice 0259 should make the authenticated session state and route guard behavior
more explicit after a credential-login success.
