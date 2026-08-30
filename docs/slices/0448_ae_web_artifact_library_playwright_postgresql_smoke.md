# Slice 0448: AE Web Artifact Library Playwright/PostgreSQL Smoke

## Intent

Add protected evidence that the AE Web artifact library can read an owner-scoped
artifact collection from the real AE API backed by the `nex_ae_test` PostgreSQL
database and render the library surface in Chromium.

## Scope

- Add `scripts/smoke/run_ae_web_artifact_library_playwright_postgres_smoke.py`.
- Add `apps/nex-ae-web/scripts/runArtifactLibraryPlaywrightSmoke.mjs`.
- Prepare a real PostgreSQL-backed artifact set with two artifacts for the same
  owner and one artifact for another owner.
- Start AE API and AE Web locally, then verify the browser calls the same-origin
  collection and detail routes.
- Keep the smoke opt-in with
  `NEX_AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_POSTGRES_SMOKE=1`.

## Evidence Boundary

- The smoke must use the test profile and reject non-test profiles.
- The live smoke must use `NEX_AE_TEST_DATABASE_URL`; no SQLite substitute is
  valid for this evidence.
- Evidence records only metadata: collection counts, selected artifact summary,
  request routes, redacted database URL, migration summary, and row counts.
- Rendered artifact payloads, storage refs, local storage paths, database
  credentials, provider endpoints, API keys, and service tokens are excluded.

## Commands

```bash
NEX_AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:nuri1004@127.0.0.1:5432/nex_ae_test \
./.venv/bin/python scripts/smoke/run_ae_web_artifact_library_playwright_postgres_smoke.py --summary
```

Default quality gate behavior remains skipped until the opt-in environment flag
is set.
