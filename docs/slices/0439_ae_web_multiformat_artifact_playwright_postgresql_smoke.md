# Slice 0439: AE Web Multiformat Artifact Playwright/PostgreSQL Smoke

## Scope

Add protected evidence that a multi-format artifact persisted in `nex_ae_test`
is visible to AE Web as a download format selector while preview/download/save
flows remain metadata-safe.

## Changes

- Extended `apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs` so browser
  evidence includes the artifact download format selector summary.
- Added
  `scripts/smoke/run_ae_web_artifact_multiformat_playwright_postgres_smoke.py`.
- Added regression coverage for the new protected smoke wrapper.
- Registered the new smoke in the default quality gate as skipped until
  explicitly enabled.

## Decisions

- The smoke first reuses the protected AE artifact export PostgreSQL smoke as an
  API/source check, then prepares a separate multi-format artifact for the
  browser route.
- The browser is given the MD artifact file for preview/download, but the
  selector must expose all persisted download formats from the artifact detail
  read-model.
- The smoke is opt-in and must use the `nex_ae_test` database with
  `NEX_AE_WEB_ARTIFACT_MULTIFORMAT_PLAYWRIGHT_POSTGRES_SMOKE=1`.

## Evidence

Targeted browser-side regression:

```bash
node --test apps/nex-ae-web/test/artifactPlaywrightSmoke.test.mjs apps/nex-ae-web/test/artifactDownloadFormatSelector.test.mjs
```

Targeted protected wrapper coverage:

```bash
./.venv/bin/pytest tests/test_ae_web_artifact_multiformat_playwright_postgres_smoke.py -q --cov=run_ae_web_artifact_multiformat_playwright_postgres_smoke --cov-branch --cov-report=term-missing
```

Protected PostgreSQL/Playwright smoke:

```bash
NEX_AE_WEB_ARTIFACT_MULTIFORMAT_PLAYWRIGHT_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://.../nex_ae_test' \
./.venv/bin/python scripts/smoke/run_ae_web_artifact_multiformat_playwright_postgres_smoke.py --summary
```

Expected protected summary shape:

```text
ae_web_artifact_multiformat_playwright_postgres_smoke=pass profile=test artifact=<artifact-id> selector=READY enabled=4 formats=4 files=4 links=8 rows=17 live_db=true browser=playwright
```
