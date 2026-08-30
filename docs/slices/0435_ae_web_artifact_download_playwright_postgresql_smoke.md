# Slice 0435: AE Web Artifact Download Playwright/PostgreSQL Smoke

## Scope

Close the S44 browser artifact delivery loop with protected evidence that a real
test-database artifact can be fetched through AE Web and prepared for browser
file save without leaking raw artifact payloads.

## Changes

- Extended `apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs` to execute
  `saveArtifactDownload` inside the Chromium page context.
- Added browser evidence checks for `browser_file_save_prepared` and
  `browser_export_result_saved`.
- Extended
  `scripts/smoke/run_ae_web_artifact_playwright_postgres_smoke.py` so protected
  PostgreSQL/Playwright evidence includes metadata-only download save and export
  result summaries.
- Updated regression coverage for the Node Playwright smoke and the protected
  Python wrapper.

## Decisions

- Browser save smoke uses native page `Blob` support and a fake document/URL
  harness. This proves materialization readiness while avoiding host OS download
  side effects.
- Raw text bodies, base64 payloads, storage refs, database URLs, service
  credentials, and provider endpoints remain forbidden in smoke evidence.
- The protected smoke is still skipped by default and only runs against the
  `nex_ae_test` database when
  `NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_POSTGRES_SMOKE=1` is explicitly set.

## Evidence

Targeted browser-side regression:

```bash
node --test apps/nex-ae-web/test/artifactPlaywrightSmoke.test.mjs apps/nex-ae-web/test/artifactExportResultReadModel.test.mjs apps/nex-ae-web/test/artifactDownloadSaveAdapter.test.mjs
```

Targeted protected wrapper coverage:

```bash
./.venv/bin/pytest tests/test_ae_web_artifact_playwright_postgres_smoke.py -q --cov=run_ae_web_artifact_playwright_postgres_smoke --cov-branch --cov-report=term-missing
```

Protected PostgreSQL/Playwright smoke:

```bash
NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://.../nex_ae_test' \
./.venv/bin/python scripts/smoke/run_ae_web_artifact_playwright_postgres_smoke.py --summary
```

Expected protected summary shape:

```text
ae_web_artifact_playwright_postgres_smoke=pass profile=test artifact=<artifact-id> version_panel=VERSION_READY preview_panel=PREVIEW_READY download_panel=DOWNLOAD_READY download_save=SAVED export_result=SAVED rows=8 live_db=true browser=playwright
```
