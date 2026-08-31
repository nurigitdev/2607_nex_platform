# Slice 0458: AE Web Artifact Lifecycle Playwright/PostgreSQL Smoke

## Goal

Add protected AE Web Playwright evidence for artifact lifecycle actions against
the real `nex_ae_test` PostgreSQL database.

## Scope

- Added a Node Playwright lifecycle smoke harness for archive, restore, and
  logical delete actions through the AE Web fetch runtime.
- Added a protected Python smoke wrapper that requires explicit opt-in and the
  AE test database URL before running.
- The smoke migrates the AE test database, prepares a rendered artifact, starts
  an AE API app and same-origin AE Web dev server, runs browser lifecycle
  actions, reads PostgreSQL state back, and cleans up smoke rows.
- Added regression coverage for skip, pass, failure, cleanup, subprocess
  parsing, and redaction branches.
- Added the protected smoke summary to the quality gate; default gate behavior
  remains skipped until explicitly enabled.

## Evidence

- `npm --prefix apps/nex-ae-web test`
  - `239 passed`
- `./.venv/bin/pytest tests/test_ae_web_artifact_lifecycle_playwright_postgres_smoke.py -q --cov=run_ae_web_artifact_lifecycle_playwright_postgres_smoke --cov-branch --cov-report=term-missing`
  - `6 passed`
  - module coverage `94%`
- Protected live smoke with `nex_ae_test`
  - `ae_web_artifact_lifecycle_playwright_postgres_smoke=pass`
  - `archive=ARCHIVED`
  - `restore=READY`
  - `delete=DELETED`
  - `deleted_rows=1`
  - `live_db=true`
  - `browser=playwright`

## Notes

- The smoke intentionally verifies logical delete only. It also checks that file
  and link rows remain present after the lifecycle transition.
- Evidence redaction rejects raw comments, database URLs, local data paths,
  service/provider secrets, and storage locations.
