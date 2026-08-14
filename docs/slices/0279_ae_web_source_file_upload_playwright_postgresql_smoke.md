# Slice 0279: AE Web Source-File Upload Playwright PostgreSQL Smoke

## Scope

Harden the protected AE Web authenticated upload smoke so it proves the
browser-selected file path, AE multipart facade, CX source-file materialization,
OA session lifecycle, and cleanup against real `test` PostgreSQL databases.

## Implemented

- Updated the AE Web Playwright upload smoke to observe multipart requests to
  `/ae-api/api/v1/uploads/files` instead of the metadata-only JSON route.
- The Node smoke records only safe booleans for multipart body shape:
  file field, owner-scope fields, hash field, content type, and redaction state.
  Raw multipart bytes are never serialized into smoke evidence.
- The Python PostgreSQL runner now:
  - uses deterministic browser test bytes and a matching SHA-256;
  - requires `nex_cx_test.cx_source_files.checksum_verified_at` to be present;
  - reports `cx_checksum=verified` in the summary line;
  - keeps AE, OA, and CX migration/test-DB evidence in the protected runner.
- Regression fixtures now fail if the smoke regresses to metadata-only upload
  semantics.

## Protected Smoke

The smoke remains skipped by default. A live run requires explicit opt-in and
real test database URLs:

```bash
NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE=1 \
NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_PROFILE=test \
NEX_AE_TEST_DATABASE_URL=... \
NEX_OA_TEST_DATABASE_URL=... \
NEX_CX_TEST_DATABASE_URL=... \
./.venv/bin/python scripts/smoke/run_ae_web_authenticated_upload_playwright_postgres_smoke.py --summary
```

## Evidence

- AE Web targeted Node smoke regression:
  `node --test apps/nex-ae-web/test/authenticatedUploadPlaywrightSmoke.test.mjs`
- Python runner regression:
  `./.venv/bin/pytest tests/test_ae_web_authenticated_upload_playwright_postgres_smoke.py -q`
- Protected PostgreSQL/Playwright smoke:
  `./.venv/bin/python scripts/smoke/run_ae_web_authenticated_upload_playwright_postgres_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
