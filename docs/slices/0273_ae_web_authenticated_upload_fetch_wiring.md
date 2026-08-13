# Slice 0273: AE Web Authenticated Upload Fetch Wiring

## Scope

Wire the authenticated upload metadata surface into a deterministic same-origin
fetch workflow. This slice proves login, OA session-claim owner scope, upload
handoff, and logout using AE Web browser clients without live network or
PostgreSQL access.

## Implemented

- Added `src/authenticatedUploadWorkflow.js`.
- Added `scripts/runAuthenticatedUploadFetchSmoke.mjs`.
- Added npm script `smoke:authenticated-upload-fetch`.
- Added `scripts/smoke/run_ae_web_authenticated_upload_fetch_smoke.py` and
  wired it into the default quality gate.
- The workflow proves:
  - current session starts anonymous;
  - credential login creates authenticated session state;
  - upload owner scope comes from OA session claims;
  - upload metadata is sent to `/api/v1/uploads` through same-origin fetch;
  - upload body contains metadata only, not raw source bytes;
  - logout returns the browser to anonymous state.

## Evidence

- AE Web Node regression:
  `npm --prefix apps/nex-ae-web test`
- Deterministic Node smoke:
  `npm --prefix apps/nex-ae-web run smoke:authenticated-upload-fetch`
- Python wrapper summary:
  `./.venv/bin/python scripts/smoke/run_ae_web_authenticated_upload_fetch_smoke.py --summary`
- Python wrapper coverage:
  `./.venv/bin/pytest tests/test_ae_web_authenticated_upload_fetch_smoke.py --cov=run_ae_web_authenticated_upload_fetch_smoke --cov-branch --cov-report=term-missing -q`

## Notes

This is not the PostgreSQL smoke. Slice 0274 should run Playwright against AE,
OA, and CX test databases and verify persisted upload evidence with redacted
readback.
