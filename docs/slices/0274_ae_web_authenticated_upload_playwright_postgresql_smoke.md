# Slice 0274: AE Web Authenticated Upload Playwright PostgreSQL Smoke

## Scope

Add protected browser smoke evidence for the authenticated upload workflow
against real test databases. This slice proves AE Web login, metadata-only
upload, AE facade auth, CX persistence, OA session revocation, and cleanup using
Playwright plus `nex_ae_test`, `nex_oa_test`, and `nex_cx_test`.

## Implemented

- Added `scripts/runAuthenticatedUploadPlaywrightSmoke.mjs` and npm script
  `smoke:authenticated-upload-playwright`.
- Added `scripts/smoke/run_ae_web_authenticated_upload_playwright_postgres_smoke.py`.
- The protected runner:
  - runs AE, OA, and CX migrations for the `test` profile;
  - seeds OA membership and credential rows;
  - starts AE API and AE Web with same-origin `/ae-api` proxying;
  - drives login, file metadata, upload submit, and logout in Playwright;
  - reads persisted upload rows back from `nex_cx_test`;
  - verifies OA session revocation in `nex_oa_test`;
  - removes smoke rows after execution.
- AE upload routes can now receive the OA session client/session mode used by
  auth-session routes, so OA-backed browser cookies are validated consistently.

## Protected Smoke

The smoke is skipped by default. A live run requires explicit opt-in and test DB
URLs:

```bash
NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE=1 \
NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_PROFILE=test \
NEX_AE_TEST_DATABASE_URL=... \
NEX_OA_TEST_DATABASE_URL=... \
NEX_CX_TEST_DATABASE_URL=... \
NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome \
./.venv/bin/python scripts/smoke/run_ae_web_authenticated_upload_playwright_postgres_smoke.py --summary
```

## Evidence

- AE Web Node regression:
  `npm --prefix apps/nex-ae-web test`
- Python runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_authenticated_upload_playwright_postgres_smoke.py --cov=run_ae_web_authenticated_upload_playwright_postgres_smoke --cov-branch --cov-report=term-missing -q`
- Protected PostgreSQL/Playwright smoke:
  `./.venv/bin/python scripts/smoke/run_ae_web_authenticated_upload_playwright_postgres_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

## Notes

The browser still sends upload metadata only: filename, content type, size, and
SHA-256. Raw source bytes stay out of browser evidence and are deferred to a
future explicit source-file storage boundary.
