# Slice 0419: AE Web Artifact PostgreSQL/Playwright Protected Smoke

## Status

Implemented.

## Scope

- Added a browser-level artifact Playwright runner for the AE Web shell.
- Added a protected Python smoke wrapper that first proves AE artifact
  PostgreSQL persistence against the test profile, then launches AE API and AE
  Web servers and runs the browser smoke.
- Wired the smoke into the quality gate as an opt-in protected check, skipped
  unless `NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_POSTGRES_SMOKE=1`.

## Evidence Contract

The protected smoke verifies:

- AE artifact migrations are current on the test database.
- Artifact handoff, artifact, version, render job, file, and link rows persist
  before browser execution.
- Chromium calls artifact detail, versions, file metadata, preview, and download
  through the same-origin `/ae-api` path.
- Browser requests do not carry service-token headers.
- Version, preview, and download panels reach ready states.
- Download content is retrieved by the client but not rendered or serialized in
  evidence.
- Smoke rows and temporary local rendered files are cleaned up.

## Commands

Default quality gate behavior:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_artifact_playwright_postgres_smoke.py --summary
```

Protected live execution requires explicit test DB configuration:

```bash
NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://.../nex_ae_test' \
./.venv/bin/python scripts/smoke/run_ae_web_artifact_playwright_postgres_smoke.py --summary
```

Expected protected summary shape:

```text
ae_web_artifact_playwright_postgres_smoke=pass profile=test version_panel=VERSION_READY preview_panel=PREVIEW_READY download_panel=DOWNLOAD_READY rows=8 live_db=true browser=playwright
```
